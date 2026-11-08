"""Giftica: автосообщение покупателю в чат Prom после нового заказа.
Запускается GitHub Actions каждые 5 минут. Токен берётся из секрета PROM_TOKEN.
Первый запуск (нет done_ids.json) только запоминает текущие заказы и никому не пишет.
"""
import json, os, sys, urllib.request, urllib.parse, uuid
from datetime import datetime, timedelta, timezone

TOKEN = os.environ["PROM_TOKEN"]
API = "https://my.prom.ua/api/v1"
STATE = "done_ids.json"
MESSAGE = (
    "Щиро дякуємо вам за замовлення та довіру до нашого магазину 💛\n\n"
    "Ми вже готуємо ваше замовлення і завтра воно буде надіслано.\n\n"
    "Дякуємо, що обрали Giftica!"
)


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


def fetch_orders(since):
    out, last_id = [], None
    for _ in range(10):
        q = {"limit": 100, "date_from": since.strftime("%Y-%m-%dT%H:%M:%S")}
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


def send(order_id):
    b = uuid.uuid4().hex
    parts = [("order_id", str(order_id)), ("body", MESSAGE)]
    data = "".join(
        f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in parts
    ) + f"--{b}--\r\n"
    code, body = req("POST", "/chat/send_order_context", data.encode("utf-8"),
                     f"multipart/form-data; boundary={b}")
    ok = code == 200
    try:
        ok = ok and json.loads(body).get("status") != "error"
    except ValueError:
        pass
    return ok, f"HTTP {code} {body[:200]}"


def main():
    first_run = not os.path.exists(STATE)
    done = set() if first_run else set(json.load(open(STATE)))
    now = datetime.now(timezone.utc)
    orders = fetch_orders(now - timedelta(days=7 if first_run else 2))

    sent = 0
    for o in orders:
        oid = o["id"]
        if oid in done:
            continue
        if first_run or o.get("status") == "canceled":
            done.add(oid)
            continue
        ok, info = send(oid)
        if ok:
            done.add(oid)
            sent += 1
            print(f"Отправлено: заказ {oid}")
        else:
            print(f"ОШИБКА: заказ {oid}: {info}")

    json.dump(sorted(done)[-800:], open(STATE, "w"))
    if first_run:
        print(f"Первый запуск: запомнено {len(done)} существующих заказов, никому не писали")
    else:
        print(f"Готово, отправлено сообщений: {sent}")


if __name__ == "__main__":
    main()
