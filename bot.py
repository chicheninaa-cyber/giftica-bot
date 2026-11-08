"""Giftica: автосообщения покупателям в чат Prom.

1) Благодарность сразу после нового заказа.
2) Просьба об отзыве со ссылкой — через 1 день после того, как заказ стал «Выполнен».

Запускается GitHub Actions каждые ~5 минут. Токен — секрет PROM_TOKEN.
При первом запуске каждой функции бот только запоминает уже существующие заказы и никому не пишет.
"""
import json, os, sys, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone

TOKEN = os.environ["PROM_TOKEN"]
API = "https://my.prom.ua/api/v1"
COMPANY_ID = 4157751  # Giftica

# --- 1. благодарность после заказа ---
THANKS_STATE = "done_ids.json"
THANKS_MESSAGE = (
    "Щиро дякуємо вам за замовлення та довіру до нашого магазину 💛\n\n"
    "Ми вже готуємо ваше замовлення і завтра воно буде надіслано.\n\n"
    "Дякуємо, що обрали Giftica!"
)

# --- 2. просьба об отзыве ---
REVIEW_STATE = "review_state.json"
REVIEW_DELAY = timedelta(days=1)  # через сколько после «Выполнен» писать
REVIEW_MESSAGE = (
    "Дякуємо за покупку! Залиште свою думку про компанію і отримайте знижку 5% "
    "на наступне замовлення✨\n{link}"
)


def review_link(order_id):
    return (f"https://prom.ua/ua/opinions/create/{COMPANY_ID}"
            f"?order_id={order_id}&page_type=portal-link_from_cabinet")


def req(method, path, data=None, content_type=None):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if content_type:
        headers["Content-Type"] = content_type
    r = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def fetch_orders(**params):
    out, last_id = [], None
    for _ in range(20):
        q = {"limit": 100, **params}
        if last_id:
            q["last_id"] = last_id
        code, body = req("GET", "/orders/list?" + urllib.parse.urlencode(q))
        if code != 200:
            sys.exit(f"Ошибка получения заказов: HTTP {code} {body[:200]}")
        page = json.loads(body).get("orders", [])
        out += page
        if len(page) < 100:
            break
        last_id = page[-1]["id"]
    return out


def send(order_id, text):
    # Prom принимает этот метод только в JSON (multipart отдаёт 400, проверено 08.11.2026)
    data = json.dumps({"order_id": order_id, "body": text}, ensure_ascii=False)
    code, body = req("POST", "/chat/send_order_context", data.encode("utf-8"),
                     "application/json")
    ok = code == 200
    try:
        ok = ok and json.loads(body).get("status") != "error"
    except ValueError:
        pass
    return ok, f"HTTP {code} {body[:200]}"


def fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def thanks(now):
    first_run = not os.path.exists(THANKS_STATE)
    done = set() if first_run else set(json.load(open(THANKS_STATE)))
    orders = fetch_orders(date_from=fmt(now - timedelta(days=7 if first_run else 2)))

    sent = 0
    for o in orders:
        oid = o["id"]
        if oid in done:
            continue
        if first_run or o.get("status") == "canceled":
            done.add(oid)
            continue
        ok, info = send(oid, THANKS_MESSAGE)
        if ok:
            done.add(oid)
            sent += 1
            print(f"Благодарность отправлена: заказ {oid}")
        else:
            print(f"ОШИБКА благодарности: заказ {oid}: {info}")

    json.dump(sorted(done)[-800:], open(THANKS_STATE, "w"))
    print("Благодарности: первый запуск, заказы запомнены" if first_run
          else f"Благодарности: отправлено {sent}")


def reviews(now):
    first_run = not os.path.exists(REVIEW_STATE)
    st = {"seen": {}, "done": []} if first_run else json.load(open(REVIEW_STATE))
    seen, done = st["seen"], set(st["done"])

    window = timedelta(days=60 if first_run else 14)
    delivered = fetch_orders(status="delivered", last_modified_from=fmt(now - window))

    sent = 0
    for o in delivered:
        key = str(o["id"])
        if o["id"] in done:
            continue
        if first_run:  # уже выполненным до запуска функции не пишем
            done.add(o["id"])
            continue
        if key not in seen:  # впервые увидели заказ «Выполнен» — запускаем отсчёт
            seen[key] = now.isoformat()
            continue
        if now - datetime.fromisoformat(seen[key]) < REVIEW_DELAY:
            continue
        ok, info = send(o["id"], REVIEW_MESSAGE.format(link=review_link(o["id"])))
        if ok:
            done.add(o["id"])
            seen.pop(key, None)
            sent += 1
            print(f"Запрос отзыва отправлен: заказ {o['id']}")
        else:
            print(f"ОШИБКА запроса отзыва: заказ {o['id']}: {info}")

    # заказы, которые вышли из «Выполнен» (например, возврат), забываем
    still = {str(o["id"]) for o in delivered}
    seen = {k: v for k, v in seen.items() if k in still}

    json.dump({"seen": seen, "done": sorted(done)[-1500:]}, open(REVIEW_STATE, "w"))
    print("Отзывы: первый запуск, выполненные заказы запомнены" if first_run
          else f"Отзывы: отправлено {sent}, ждут 1 день: {len(seen)}")


def main():
    now = datetime.now(timezone.utc)
    thanks(now)
    reviews(now)


if __name__ == "__main__":
    main()
