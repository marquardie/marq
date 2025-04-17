# Вказуємо базовий образ Python
FROM python:3.11-slim

# Встановлюємо робочу директорію
WORKDIR /app

# Копіюємо всі файли в контейнер
COPY . /app

# Встановлюємо залежності
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Вказуємо команду, яка запускає бота
CMD ["python", "Cleaner_bot.py"]
