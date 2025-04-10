from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO
import paramiko
import pandas as pd
from io import BytesIO
import time
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import eventlet

eventlet.monkey_patch()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='eventlet')

# Глобальные переменные для хранения состояния
devices = []
credentials = []
commands = []
results = {}
execution_in_progress = False
stop_event = False
executor = None
thread_lock = Lock()

# Настройки по умолчанию
DEFAULT_SETTINGS = {
    'max_workers': 3,
    'command_timeout': 10,
    'delay_between_commands': 2,
    'auto_scroll': True
}
current_settings = DEFAULT_SETTINGS.copy()


@app.route('/')
def index():
    """Главная страница приложения"""
    return render_template('index.html',
                           settings=current_settings,
                           default_settings=DEFAULT_SETTINGS)


@app.route('/upload', methods=['POST'])
def upload_file():
    """Загрузка файла с устройствами"""
    global devices, credentials

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    try:
        # Чтение Excel-файла
        df = pd.read_excel(file)
        if len(df.columns) < 3:
            raise ValueError("Файл должен содержать минимум 3 столбца")

        # Получаем уникальные IP-адреса
        devices = df.iloc[:, 0].dropna().astype(str).unique().tolist()

        # Получаем уникальные пары логин/пароль
        creds = df.iloc[:, 1:3].dropna()
        credentials = list(set(zip(
            creds.iloc[:, 0].astype(str),
            creds.iloc[:, 1].astype(str)
        )))

        socketio.emit('log', {'message': f"Загружено {len(devices)} устройств и {len(credentials)} учетных записей"})
        return jsonify({
            'success': True,
            'devices_count': len(devices),
            'credentials_count': len(credentials)
        })

    except Exception as e:
        socketio.emit('log', {'message': f"Ошибка загрузки файла: {str(e)}"})
        return jsonify({'error': str(e)}), 500


@app.route('/set_commands', methods=['POST'])
def set_commands():
    """Установка команд для выполнения"""
    global commands
    data = request.json
    commands = [cmd.strip() for cmd in data.get('commands', []) if cmd.strip()]

    if not commands:
        return jsonify({'error': 'No commands provided'}), 400

    socketio.emit('log', {'message': f"Установлено {len(commands)} команд для выполнения"})
    return jsonify({'success': True, 'commands_count': len(commands)})


@app.route('/set_settings', methods=['POST'])
def set_settings():
    """Обновление настроек"""
    global current_settings
    data = request.json

    try:
        current_settings.update({
            'max_workers': int(data.get('max_workers', current_settings['max_workers'])),
            'command_timeout': int(data.get('command_timeout', current_settings['command_timeout'])),
            'delay_between_commands': int(
                data.get('delay_between_commands', current_settings['delay_between_commands'])),
            'auto_scroll': bool(data.get('auto_scroll', current_settings['auto_scroll']))
        })

        socketio.emit('log', {'message': "Настройки успешно обновлены"})
        return jsonify({'success': True, 'settings': current_settings})

    except Exception as e:
        socketio.emit('log', {'message': f"Ошибка обновления настроек: {str(e)}"})
        return jsonify({'error': str(e)}), 400


@socketio.on('start_execution')
def handle_start_execution():
    """Запуск выполнения команд"""
    global execution_in_progress, stop_event, executor

    # Проверка наличия необходимых данных
    if not devices:
        socketio.emit('log', {'message': "Ошибка: Не загружены устройства"})
        return
    if not credentials:
        socketio.emit('log', {'message': "Ошибка: Не загружены учетные данные"})
        return
    if not commands:
        socketio.emit('log', {'message': "Ошибка: Не указаны команды для выполнения"})
        return

    # Инициализация состояния выполнения
    with thread_lock:
        if execution_in_progress:
            socketio.emit('log', {'message': "Выполнение уже запущено"})
            return

        execution_in_progress = True
        stop_event = False
        results.clear()

    # Запуск выполнения в отдельном потоке
    socketio.start_background_task(target=execute_commands)
    socketio.emit('execution_started')


def execute_commands():
    """Основная функция выполнения команд"""
    global execution_in_progress, stop_event, results

    try:
        socketio.emit('log', {'message': f"Начато выполнение на {len(devices)} устройствах"})
        socketio.emit('status_update', {'status': 'running', 'devices_total': len(devices)})

        with ThreadPoolExecutor(max_workers=current_settings['max_workers']) as executor:
            futures = {executor.submit(process_device, ip): ip for ip in devices}

            for future in as_completed(futures):
                if stop_event:
                    executor.shutdown(wait=False)
                    break

                ip = futures[future]
                try:
                    future.result()
                except Exception as e:
                    socketio.emit('log', {'message': f"Ошибка обработки устройства {ip}: {str(e)}"})

        # Формирование итогового отчета
        success_count = sum(1 for res in results.values() if res['success'])
        socketio.emit('log', {'message': f"\nВыполнение завершено. Успешно: {success_count}/{len(devices)}"})
        socketio.emit('status_update', {
            'status': 'completed',
            'devices_total': len(devices),
            'success_count': success_count
        })

    except Exception as e:
        socketio.emit('log', {'message': f"Критическая ошибка выполнения: {str(e)}"})

    finally:
        with thread_lock:
            execution_in_progress = False
            stop_event = False


def process_device(ip):
    """Обработка одного устройства"""
    global results, stop_event

    if stop_event:
        return

    socketio.emit('log', {'message': f"\nОбработка устройства: {ip}"})
    socketio.emit('device_start', {'ip': ip})

    # Инициализация записи результатов
    results[ip] = {
        'success': False,
        'credentials': None,
        'output': "",
        'errors': []
    }

    # Подключение к устройству
    ssh = connect_to_device(ip)
    if not ssh:
        socketio.emit('device_end', {'ip': ip, 'success': False})
        return

    try:
        # Выполнение всех команд на устройстве
        for cmd in commands:
            if stop_event:
                break

            # Выполняем команду и сохраняем вывод
            command_output = execute_single_command(ssh, ip, cmd)
            results[ip]['output'] += f"\nКоманда: {cmd}\n{command_output}\n"

        # Помечаем как успешное, если не было ошибок
        if not results[ip]['errors']:
            results[ip]['success'] = True
            socketio.emit('device_end', {'ip': ip, 'success': True})

    except Exception as e:
        error_msg = f"Ошибка выполнения на {ip}: {str(e)}"
        results[ip]['errors'].append(error_msg)
        socketio.emit('log', {'message': error_msg})
        socketio.emit('device_output', {'ip': ip, 'output': f"\n{error_msg}\n"})

    finally:
        # Закрываем соединение
        ssh.close()
        socketio.emit('log', {'message': f"Отключено от {ip}"})


def connect_to_device(ip):
    """Подключение к устройству с перебором учетных данных"""
    global results

    for user, pwd in credentials:
        try:
            socketio.emit('log', {'message': f"Попытка подключения: {user}/{pwd}"})
            socketio.emit('device_output', {'ip': ip, 'output': f"Попытка подключения: {user}/{'*' * len(pwd)}\n"})

            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username=user, password=pwd, timeout=10)

            socketio.emit('log', {'message': f"Успешное подключение к {ip} с {user}"})
            socketio.emit('device_output', {'ip': ip, 'output': f"Подключено с: {user}\n\n"})

            # Сохраняем использованные учетные данные
            results[ip]['credentials'] = f"{user}/{pwd}"
            return ssh

        except Exception as e:
            error_msg = f"Ошибка подключения с {user}: {str(e)}"
            results[ip]['errors'].append(error_msg)
            socketio.emit('log', {'message': error_msg})
            socketio.emit('device_output', {'ip': ip, 'output': f"{error_msg}\n"})
            if 'ssh' in locals():
                ssh.close()

    error_msg = f"Не удалось подключиться к {ip}"
    results[ip]['errors'].append(error_msg)
    socketio.emit('device_output', {'ip': ip, 'output': f"\n{error_msg}\n"})
    socketio.emit('log', {'message': error_msg})
    return None


def execute_single_command(ssh, ip, cmd):
    """Выполнение одной команды на устройстве"""
    global stop_event

    socketio.emit('log', {'message': f"Выполнение команды: {cmd}"})
    socketio.emit('device_output', {'ip': ip, 'output': f"Команда:\n{cmd}\n\n"})

    channel = ssh.get_transport().open_session()
    channel.exec_command(cmd)
    channel.setblocking(0)

    start_time = time.time()
    output = ""

    while not stop_event:
        # Чтение стандартного вывода
        while channel.recv_ready():
            data = channel.recv(1024).decode('utf-8')
            output += data
            socketio.emit('device_output', {'ip': ip, 'output': data})

        # Чтение вывода ошибок
        while channel.recv_stderr_ready():
            error_data = channel.recv_stderr(1024).decode('utf-8')
            output += error_data
            socketio.emit('device_output', {'ip': ip, 'output': error_data})

        # Проверка завершения команды
        if channel.exit_status_ready() or (time.time() - start_time) > current_settings['command_timeout']:
            break

        time.sleep(0.1)

    # Обработка завершения команды
    exit_status = -1
    if channel.exit_status_ready():
        exit_status = channel.recv_exit_status()
        status_msg = f"\nКоманда завершена с кодом: {exit_status}\n"
    else:
        channel.close()
        status_msg = f"\nПревышено время ожидания ({current_settings['command_timeout']} сек)\n"

    socketio.emit('device_output', {'ip': ip, 'output': status_msg})
    output += status_msg

    # Задержка между командами, если не была нажата остановка
    if not stop_event:
        time.sleep(current_settings['delay_between_commands'])

    return output


@socketio.on('stop_execution')
def handle_stop_execution():
    """Остановка выполнения команд"""
    global stop_event

    with thread_lock:
        stop_event = True

    socketio.emit('log', {'message': "Выполнение остановлено пользователем"})
    socketio.emit('status_update', {'status': 'stopped'})


@app.route('/download_results')
def download_results():
    """Скачивание результатов выполнения"""
    if not results or all(not res['output'] for res in results.values()):
        return jsonify({'error': 'No results to download'}), 400

    try:
        # Создаем файл в памяти
        output = BytesIO()

        # Заголовок отчета
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output.write(f"{'=' * 60}\n".encode('utf-8'))
        output.write(f"Parallel SSH Commander - Отчет\n".encode('utf-8'))
        output.write(f"Дата создания: {timestamp}\n".encode('utf-8'))
        output.write(f"{'=' * 60}\n\n".encode('utf-8'))

        # Общая информация
        success_count = sum(1 for res in results.values() if res['success'])
        output.write(f"Всего устройств: {len(results)}\n".encode('utf-8'))
        output.write(f"Успешных подключений: {success_count}\n".encode('utf-8'))
        output.write(f"Ошибок подключения: {len(results) - success_count}\n\n".encode('utf-8'))

        # Выполненные команды
        output.write("Выполненные команды:\n".encode('utf-8'))
        for i, cmd in enumerate(commands, 1):
            output.write(f"{i}. {cmd}\n".encode('utf-8'))
        output.write("\n".encode('utf-8'))

        # Результаты по устройствам
        for ip, result in results.items():
            output.write(f"{'-' * 60}\n".encode('utf-8'))
            output.write(f"Устройство: {ip}\n".encode('utf-8'))
            output.write(f"Статус: {'УСПЕШНО' if result['success'] else 'ОШИБКА'}\n".encode('utf-8'))

            if result['credentials']:
                output.write(f"Учетные данные: {result['credentials']}\n".encode('utf-8'))

            if result['errors']:
                output.write("\nОшибки:\n".encode('utf-8'))
                for error in result['errors']:
                    output.write(f"• {error}\n".encode('utf-8'))

            output.write("\nВывод команд:\n".encode('utf-8'))
            output.write(result['output'].encode('utf-8'))
            output.write("\n".encode('utf-8'))

        output.seek(0)
        filename = f"ssh_results_{timestamp}.txt"

        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='text/plain'
        )

    except Exception as e:
        socketio.emit('log', {'message': f"Ошибка создания файла результатов: {str(e)}"})
        return jsonify({'error': str(e)}), 500


@app.route('/clear_all')
def clear_all():
    """Очистка всех данных"""
    global devices, credentials, commands, results

    devices = []
    credentials = []
    commands = []
    results = {}

    socketio.emit('log', {'message': "Все данные очищены"})
    return jsonify({'success': True})


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)