import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os

# --- НАСТРОЙКИ (переменные окружения) ---
EMAIL_HOST = os.getenv("SMTP_SERVER_OUT")
EMAIL_PORT = int(os.getenv("EMAIL_PORT_OUT", 587))
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT_OUT")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD_OUT")
# -------------------------------------

# Изменена функция: теперь она принимает список recipients
def send_mail(subject, body, recipients, attachments=[]):
    # Проверяем, что все нужные переменные окружения заданы
    if not all([EMAIL_HOST, EMAIL_ACCOUNT, EMAIL_PASSWORD, recipients]):
        print("[-] Ошибка: Настройки email неполные. Проверьте переменные окружения.")
        return

    try:
        # Создаем сообщение
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ACCOUNT
        # Объединяем список получателей в одну строку через запятую
        msg['To'] = ", ".join(recipients) 
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        # Прикрепляем файлы
        for attachment_path in attachments:
            if not os.path.exists(attachment_path):
                print(f"[-] Файл вложения не найден: {attachment_path}")
                continue
            
            part = MIMEBase('application', 'octet-stream')
            with open(attachment_path, 'rb') as file:
                part.set_payload(file.read())
            
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f"attachment; filename= {os.path.basename(attachment_path)}")
            msg.attach(part)

        # Подключаемся к серверу, входим в аккаунт и отправляем письмо
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
            # Отправляем письмо всем получателям
            server.sendmail(EMAIL_ACCOUNT, recipients, msg.as_string())
        
        print("[+] Письмо успешно отправлено.")

    except Exception as e:
        print(f"[-] Ошибка при отправке письма: {e}")
