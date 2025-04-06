import os
import PyInstaller.__main__

# Определите путь к вашему основному скрипту
script_path = os.path.join(os.path.dirname(__file__), 'main.py')

# Параметры сборки
PyInstaller.__main__.run([
    script_path,
    '--onefile',          # Создать один исполняемый файл
    '--windowed',         # Не показывать консоль (для GUI приложений)
    '--icon=app.ico',     # Иконка приложения (необязательно)
    '--name=SSH_Commander',  # Имя выходного файла
    '--add-data=assets;assets'  # Добавить дополнительные файлы (если есть)
])