import os
import time
import shutil
import cv2
import requests
import json
from ultralytics import YOLO

# --- Пороговые значения по классам ---
# Ключ = ID класса YOLO, значение = минимальный порог уверенности
CLASS_THRESHOLDS = {
    0: 0.5,  # person
    1: 0.2,  # bicycle
    2: 0.1,  # car
    3: 0.1,  # motorcycle
    5: 0.1,  # bus
    7: 0.1,  # truck
    8: 0.25   # train
}
DEFAULT_CONFIDENCE = 0.3  # fallback для классов без явного порога

# --- попытка импортировать почтовый модуль ---
try:
    from mailer import send_mail
except ImportError:
    def send_mail(subject, body, recipients=None, attachments=None):
        print(f"[!] Почтовый модуль не найден. Письмо '{subject}' не отправлено.")
        return

# --- НАСТРОЙКИ TELEGRAM ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GENERAL_CHAT_ID = os.getenv("GENERAL_CHAT_ID")

# --- КОНФИГУРАЦИЯ КАМЕР ---
CAMERA_SETTINGS = {
    "vorota1": {
        "desired_classes": [1, 2, 3, 5, 6, 7, 8],
        "send_email": False,
        "email_receivers": [os.getenv("GENERAL_EMAIL")],
        "send_telegram": True,
        "telegram_chat_ids": [os.getenv("TELEGRAM_CHAT_ID_1"), GENERAL_CHAT_ID]
#        "telegram_chat_ids": [GENERAL_CHAT_ID]
    },
    "vorota2": {
        "desired_classes": [0, 1, 2, 3, 4, 5, 7, 8],
        "send_email": True,
        "email_receivers": [os.getenv("EMAIL_RECEIVER_1"), os.getenv("EMAIL_RECEIVER_2")],
        "send_telegram": True,
        "telegram_chat_ids": [GENERAL_CHAT_ID]
    },
    "vorota3": {
        "desired_classes": [0, 2, 5],
#        "send_email": False,
        "email_receivers": [],
        "send_telegram": False,
#        "telegram_chat_ids": [os.getenv("TELEGRAM_CHAT_ID_2")]
        "telegram_chat_ids": []
    },
    "default": {
        "desired_classes": [0, 1, 2, 3, 5, 6, 7, 8],
        "send_email": True,
        "email_receivers": [os.getenv("GENERAL_EMAIL")],
        "send_telegram": True,
        "telegram_chat_ids": [GENERAL_CHAT_ID]
    }
}
##############################
print("GENERAL_EMAIL:", os.getenv("GENERAL_EMAIL"))
print("EMAIL_RECEIVER_1:", os.getenv("EMAIL_RECEIVER_1"))
print("EMAIL_RECEIVER_2:", os.getenv("EMAIL_RECEIVER_2"))
######################


# --- Папки ---
INBOX = "/data/inbox"
FILTERED = "/data/filtered"
REJECTED = "/data/rejected"
TELEGRAM_QUEUE = "/data/telegram-queue"

for folder in [INBOX, FILTERED, REJECTED, TELEGRAM_QUEUE]:
    os.makedirs(folder, exist_ok=True)

# --- инициализация YOLO ---
model = YOLO("yolov8m.pt")

# =============================
def send_telegram_notification(photo_path, camera_name, event_date, event_time, detected_labels, chat_ids):
    if not TELEGRAM_BOT_TOKEN or not chat_ids:
        print(f"[-] Ошибка: токен или ID чатов для камеры {camera_name} не настроены.")
        return

    telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    caption = f"*{camera_name}*: {', '.join(detected_labels)}\n`{event_date} {event_time.replace('-', ':')}`"

    for chat_id in chat_ids:
        try:
            with open(photo_path, "rb") as photo_file:
                files = {'photo': photo_file}
                data = {
                    'chat_id': chat_id,
                    'caption': caption,
                    'parse_mode': 'Markdown'
                }
                response = requests.post(telegram_api_url, files=files, data=data)
                if response.status_code == 200:
                    print(f"[+] Уведомление для {camera_name} отправлено в чат {chat_id}.")
                else:
                    print(f"[-] Ошибка Telegram ({chat_id}): {response.text}")
                    save_to_telegram_queue(photo_path, camera_name, event_date, event_time, detected_labels, [chat_id])
        except Exception as e:
            print(f"[-] Ошибка Telegram ({chat_id}): {e}")
            save_to_telegram_queue(photo_path, camera_name, event_date, event_time, detected_labels, [chat_id])

# ========================
def save_to_telegram_queue(photo_path, camera_name, event_date, event_time, detected_labels, chat_ids):
    queue_file_name = f"{os.path.basename(photo_path)}_{int(time.time())}.json"
    queue_file_path = os.path.join(TELEGRAM_QUEUE, queue_file_name)

    data_to_save = {
        "photo_path": photo_path,
        "camera_name": camera_name,
        "event_date": event_date,
        "event_time": event_time,
        "detected_labels": detected_labels,
        "chat_ids": chat_ids
    }

    with open(queue_file_path, 'w') as f:
        json.dump(data_to_save, f)

    print(f"[!] Уведомление сохранено в очередь: {queue_file_path}")


def has_desired_objects(image_path, camera_settings):
    try:
        results = model(image_path, conf=0.1, imgsz=640)  # базовый очень низкий порог
        desired_classes = camera_settings.get("desired_classes", [])
        found_objects = False
        detected_labels = []

        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0].item())
                conf = float(box.conf[0].item())
                threshold = CLASS_THRESHOLDS.get(cls_id, DEFAULT_CONFIDENCE)

                if cls_id in desired_classes and conf >= threshold:
                    found_objects = True
                    label = model.names.get(cls_id, f"class_{cls_id}")
                    if label not in detected_labels:
                        detected_labels.append(label)

        return found_objects, results, detected_labels
    except Exception as e:
        print(f"[-] Ошибка обработки {image_path}: {e}")
        return False, None, []


if __name__ == "__main__":
    print("[*] Запущен мониторинг папки INBOX...")
    while True:
        for filename in os.listdir(INBOX):
            path = os.path.join(INBOX, filename)
            if not os.path.isfile(path):
                continue

            print(f"[+] Обнаружен новый файл: {filename}")

            try:
                parts = filename.split('_')
                if len(parts) < 4:
                    print(f"[-] Пропускаем файл с некорректным именем: {filename}")
                    shutil.move(path, os.path.join(REJECTED, filename))
                    continue

                camera_name = parts[0]
                event_date = parts[1]
                event_time = parts[2]

                settings = CAMERA_SETTINGS.get(camera_name, CAMERA_SETTINGS["default"])
                found, detection_results, detected_labels = has_desired_objects(path, settings)

                if found:
                    annotated_image = cv2.imread(path)
                    frame_color = (0, 255, 200)
                    line_thickness = 1

                    for r in detection_results:
                        for box in r.boxes:
                            cls_id = int(box.cls[0].item())
                            conf = float(box.conf[0].item())
                            threshold = CLASS_THRESHOLDS.get(cls_id, DEFAULT_CONFIDENCE)
                            if cls_id in settings.get("desired_classes", []) and conf >= threshold:
                                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                                cv2.rectangle(annotated_image, (x1, y1), (x2, y2), frame_color, line_thickness)

                    name, ext = os.path.splitext(filename)
                    annotated_filename = f"{name}_with_detections{ext}"
                    output_path = os.path.join(FILTERED, annotated_filename)
                    cv2.imwrite(output_path, annotated_image)
                    shutil.move(path, os.path.join(FILTERED, filename))

                    detected_text = ", ".join(set(detected_labels))
                    print(f"[+] Объекты '{detected_text}' найдены на {camera_name}.")

                    if settings.get("send_email", False) is True:
                         subject = f"Обнаружены объекты на камере (условно): {camera_name}"
                         body = f"{camera_name} условно найдены: {detected_text}."
                         email_receivers = settings.get("email_receivers", [])
                         if email_receivers:
                     # Отправляем отдельное письмо каждому получателю
                            for receiver in email_receivers:
                                if receiver and receiver.strip():  # Проверяем, что адрес не пустой
                                    send_mail(subject, body, recipients=[receiver], attachments=[output_path])


            #        if settings.get("send_email", False) is True:
            #            subject = f"Обнаружены объекты на камере (условно): {camera_name}"
            #            body = f"{camera_name} условно найдены: {detected_text}."
            #            email_receivers = settings.get("email_receivers", [])
            #            if email_receivers:
            #                send_mail(subject, body, recipients=email_receivers, attachments=[output_path])

                    if settings.get("send_telegram", False):
                        telegram_chat_ids = settings.get("telegram_chat_ids")
                        send_telegram_notification(output_path, camera_name, event_date, event_time, detected_labels, telegram_chat_ids)

                else:
                    save_path = os.path.join(REJECTED, filename)
                    shutil.move(path, save_path)
                    print(f"[-] Нет объектов для {camera_name}. Файл перемещён.")

            except Exception as e:
                print(f"[-] Ошибка обработки {path}: {e}")

        time.sleep(10)

