import imaplib
import email
import os
import time
import re
import uuid
import html
import cv2
import numpy as np

# --- НАСТРОЙКИ ---
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
IMAP_SERVER = os.getenv("IMAP_SERVER")
USE_SSL = os.getenv("USE_SSL", "False").lower() == "true"
MAX_ATTACHMENTS = min(int(os.getenv("MAX_ATTACHMENTS", "3")), 5)
SAVE_PATH = "/data/inbox"
IMAGE_SIMILARITY_THRESHOLD = 0.98
# -----------------

os.makedirs(SAVE_PATH, exist_ok=True)

def get_image_histogram(image_data):
    try:
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            print(f"[-] Не удалось декодировать изображение.")
            return None
        hist = cv2.calcHist([img], [0], None, [256], [0, 256])
        hist = cv2.normalize(hist, hist).flatten()
        return hist
    except Exception as e:
        print(f"[-] Ошибка при вычислении гистограммы: {e}")
        return None

def is_image_similar(current_image_data, processed_histograms):
    current_hist = get_image_histogram(current_image_data)
    if current_hist is None:
        return True
    for prev_hist in processed_histograms:
        if prev_hist is None:
            continue
        similarity = cv2.compareHist(current_hist, prev_hist, cv2.HISTCMP_CORREL)
        if similarity > IMAGE_SIMILARITY_THRESHOLD:
            return True
    return False

def clean_and_normalize_html(raw_html):
    if not raw_html or not isinstance(raw_html, str):
        return ""
    normalized_html = re.sub(r'(?i)<br\s*/?>', '\n', raw_html)
    cleanr = re.compile('<.*?>', re.IGNORECASE)
    cleaned_text = re.sub(cleanr, '', normalized_html)
    return html.unescape(cleaned_text)

def save_attachment(part, camera_name, event_date, event_time, attachment_index):
    filename = part.get_filename() or f"attachment_{uuid.uuid4().hex}"
    base, ext = os.path.splitext(filename)
    clean_camera_name = re.sub(r'[^a-zA-Z0-9_]+', '', camera_name) if camera_name else "unknown_cam"
    clean_event_time = event_time.replace(':', '-') if event_time else "unknown_time"
    clean_event_date = event_date if event_date else "unknown_date"
    new_filename = f"{clean_camera_name}_{clean_event_date}_{clean_event_time}_{attachment_index}{ext}"
    filepath = os.path.join(SAVE_PATH, new_filename)
    with open(filepath, "wb") as f:
        f.write(part.get_payload(decode=True))
    print(f"[+] Скачан и переименован файл: {filepath}")
    return filepath

def fetch_mail():
    mail_class = imaplib.IMAP4_SSL if USE_SSL else imaplib.IMAP4
    mail = None
    try:
#        print(f"[DEBUG] Подключение к {IMAP_SERVER}, SSL={USE_SSL}, логин={EMAIL_ACCOUNT}")
        mail = mail_class(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
#        print("[DEBUG] Успешный логин")

        status, _ = mail.select("inbox")
#        print(f"[DEBUG] Выбор папки INBOX: {status}")

        status, messages = mail.search(None, "UNSEEN")
        message_ids = messages[0].split()
#        print(f"[DEBUG] Найдено непрочитанных писем: {len(message_ids)}")

        if not message_ids:
            print("Нет новых писем.")
            return

        messages_with_dates = []
        for num in message_ids:
            status, msg_data = mail.fetch(num, "(INTERNALDATE)")
#            print(f"[DEBUG] INTERNALDATE для {num.decode()}: {msg_data}")

            if not msg_data or not msg_data[0]:
#                print(f"[-] INTERNALDATE пуст для письма {num.decode()}")
                continue

            try:
                date_tuple = imaplib.Internaldate2tuple(msg_data[0])
                if date_tuple:
                    messages_with_dates.append({'id': num, 'date': time.mktime(date_tuple)})
                else:
                    print(f"[-] Не удалось распарсить дату письма {num.decode()}: {msg_data[0]}")
                    # если не получилось — добавляем без сортировки
                    messages_with_dates.append({'id': num, 'date': time.time()})
            except Exception as e:
                print(f"[ERROR] Ошибка парсинга INTERNALDATE письма {num.decode()}: {e}")
                messages_with_dates.append({'id': num, 'date': time.time()})

        # сортировка по дате
        messages_with_dates.sort(key=lambda x: x['date'])
        sorted_message_ids = [msg['id'] for msg in messages_with_dates]

        for num in sorted_message_ids:
#            print(f"[DEBUG] Обработка письма {num.decode()}")
            status, msg_data = mail.fetch(num, "(RFC822)")
            if not msg_data or not msg_data[0]:
                print(f"[-] Ошибка получения письма {num.decode()}")
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            # --- обработка тела письма ---
            email_body = ""
            for part in msg.walk():
                if part.get_content_maintype() == 'text':
                    try:
                        charset = part.get_content_charset()
                        payload = part.get_payload(decode=True)
#                        print(f"[DEBUG] Текстовая часть письма, charset={charset}, длина={len(payload) if payload else 0}")
                        email_body += payload.decode(charset or 'utf-8', errors='ignore')
                    except Exception as e:
                        print(f"Ошибка декодирования части письма: {e}")

            if "<html" in email_body.lower():
                email_body = clean_and_normalize_html(email_body)
                print("[DEBUG] Тело письма содержит HTML → нормализовано.")

            # --- поиск камеры и времени ---
            camera_name = ""
            event_date = ""
            event_time = ""

            lines = email_body.splitlines()
            for line in lines:
                print(f"[DEBUG] Строка письма: {line}")
                if "CAMERA NAME(NUM):" in line:
                    camera_info = line.replace("CAMERA NAME(NUM):", "").strip()
                    camera_name = camera_info.split('(')[0].strip()
#                    print(f"[DEBUG] Имя камеры: {camera_name}")
                if "EVENT TIME:" in line:
                    time_info = line.replace("EVENT TIME:", "").strip()
                    if ',' in time_info:
                        event_date, event_time = time_info.split(',')
                        event_date = event_date.strip()
                        event_time = event_time.strip()
#                        print(f"[DEBUG] Дата/время события: {event_date} {event_time}")

            # --- вложения ---
            processed_histograms_in_email = []
            attachment_index = 0
            for part in msg.walk():
                if part.get_content_maintype() == "multipart" or not part.get("Content-Disposition"):
                    continue
                if not part.get_content_type().startswith('image/'):
                    continue
                if attachment_index >= MAX_ATTACHMENTS:
                    print(f"[-] Достигнут лимит вложений ({MAX_ATTACHMENTS}). Пропускаем остальные.")
                    break

                print(f"[DEBUG] Обработка вложения {attachment_index+1}, type={part.get_content_type()}")
                current_image_data = part.get_payload(decode=True)
                current_hist = get_image_histogram(current_image_data)

                if current_hist is None:
                    print(f"[-] Не удалось получить гистограмму. Пропускаем вложение.")
                    continue

                if is_image_similar(current_image_data, processed_histograms_in_email):
                    print(f"[-] Пропускаем визуально схожее вложение (дубликат).")
                    continue
                else:
                    processed_histograms_in_email.append(current_hist)
                    attachment_index += 1
                    save_attachment(part, camera_name, event_date, event_time, attachment_index)

            # --- удаление письма ---
            print(f"[DEBUG] Попытка пометить письмо {num.decode()} для удаления...")
            status_delete, response_delete = mail.store(num, '+FLAGS', '\\Deleted')
            print(f"[DEBUG] Результат пометки: {status_delete}, {response_delete}")

            status_flags, response_flags = mail.fetch(num, '(FLAGS)')
            print(f"[DEBUG] Флаги письма {num.decode()}: {response_flags[0].decode() if response_flags and response_flags[0] else 'None'}")
            print(f"[+] Письмо {num.decode()} помечено для удаления.")

        # --- expunge ---
        print("[DEBUG] Выполняем EXPUNGE...")
        status_expunge, response_expunge = mail.expunge()
        print(f"[DEBUG] EXPUNGE → {status_expunge}, {response_expunge}")
        print("[+] Все помеченные письма удалены.")
    except Exception as e:
        print(f"[ERROR] Ошибка при работе с IMAP: {e}")
    finally:
        if mail and mail.state == 'SELECTED':
            try:
                mail.logout()
                print("[DEBUG] Соединение закрыто.")
            except Exception as e:
                print(f"[-] Ошибка при закрытии IMAP: {e}")

if __name__ == "__main__":
    try:
        while True:
            try:
                fetch_mail()
            except Exception as e:
                print(f"[ERROR] Ошибка при получении почты: {e}")
            time.sleep(60)
    except KeyboardInterrupt:
        print("Прервано пользователем.")
