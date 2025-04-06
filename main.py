import os
import time
import paramiko
import pandas as pd
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from threading import Thread, Event, Semaphore
from queue import Queue
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageTk
import sys
import select
from concurrent.futures import ThreadPoolExecutor, as_completed


class SSHClientApp:
    def __init__(self, root):
        """Инициализация главного окна приложения"""
        self.root = root
        self.root.title("Parallel SSH Commander")
        self.root.geometry("1200x800")

        # Параметры выполнения
        self.max_workers = 5  # Максимальное количество одновременных подключений
        self.semaphore = Semaphore(self.max_workers)
        self.stop_event = Event()
        self.command_timeout = 10  # Таймаут выполнения команды (сек)
        self.delay = 3  # Задержка между командами (сек)

        # Структуры данных
        self.ip_list = []  # Список IP-адресов устройств
        self.credentials = []  # Список учетных данных (логин, пароль)
        self.commands = []  # Список команд для выполнения
        self.results = {}  # Результаты выполнения (исправлено: теперь сохраняет правильно)
        self.active_tabs = {}  # Активные вкладки устройств
        self.output_queue = Queue()  # Очередь для вывода сообщений

        # Инициализация интерфейса
        self.create_widgets()
        self.create_watermark()
        self.check_queue()

    def create_watermark(self):
        """Создание водяного знака"""
        watermark = Image.new('RGBA', (250, 100), (255, 255, 255, 0))
        draw = ImageDraw.Draw(watermark)
        try:
            font = ImageFont.truetype("arial.ttf", 24)
        except:
            font = ImageFont.load_default()
        draw.text((10, 10), "FGMP1790", fill=(150, 150, 150, 100), font=font)
        self.watermark_image = ImageTk.PhotoImage(watermark)
        self.watermark_label = tk.Label(self.root, image=self.watermark_image, bd=0)
        self.watermark_label.place(relx=0.01, rely=0.98, anchor='sw')

    def create_widgets(self):
        """Создание интерфейса"""
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Левая панель
        left_panel = tk.Frame(main_frame, width=400)
        left_panel.pack(side=tk.LEFT, fill=tk.Y)
        left_panel.pack_propagate(False)

        # Описание формата
        desc_frame = tk.LabelFrame(left_panel, text="Формат Excel-файла", padx=5, pady=5)
        desc_frame.pack(fill=tk.X, padx=5, pady=5)

        desc_text = """Excel-файл должен содержать:
1. Первый столбец - IP-адреса устройств
2. Второй столбец - логины
3. Третий столбец - пароли"""

        tk.Label(desc_frame, text=desc_text, justify=tk.LEFT).pack(padx=5, pady=5)

        # Загрузка файла
        file_frame = tk.LabelFrame(left_panel, text="Загрузить Excel-файл", padx=5, pady=5)
        file_frame.pack(fill=tk.X, padx=5, pady=5)

        self.file_path = tk.StringVar()
        tk.Entry(file_frame, textvariable=self.file_path, state='readonly').pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(file_frame, text="Обзор", command=self.browse_file).pack(side=tk.RIGHT)

        # Ввод команд
        cmd_frame = tk.LabelFrame(left_panel, text="Команды для выполнения", padx=5, pady=5)
        cmd_frame.pack(fill=tk.X, padx=5, pady=5)

        self.command_entries = []
        for i in range(5):
            row_frame = tk.Frame(cmd_frame)
            row_frame.pack(fill=tk.X, pady=2)
            tk.Label(row_frame, text=f"Команда {i + 1}:", width=10).pack(side=tk.LEFT)
            entry = tk.Entry(row_frame)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.command_entries.append(entry)

        # Кнопки управления
        btn_frame = tk.Frame(left_panel)
        btn_frame.pack(fill=tk.X, padx=5, pady=10)

        tk.Button(btn_frame, text="Выполнить", command=self.start_execution).pack(side=tk.LEFT, expand=True)
        tk.Button(btn_frame, text="Сохранить", command=self.save_results).pack(side=tk.LEFT, expand=True)
        tk.Button(btn_frame, text="Очистить", command=self.clear_all).pack(side=tk.LEFT, expand=True)

        # Правая панель
        right_panel = tk.Frame(main_frame)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Вкладки
        self.notebook = ttk.Notebook(right_panel)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Вкладка логов
        self.create_log_tab()

        # Статус бар
        self.status_var = tk.StringVar()
        self.status_var.set("Готов к работе")
        status_bar = tk.Label(self.root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Счетчик устройств
        self.tab_counter = tk.Label(self.root, text="Устройств: 0", bd=1, relief=tk.SUNKEN)
        self.tab_counter.pack(side=tk.BOTTOM, fill=tk.X)

    def create_log_tab(self):
        """Создает вкладку для логов"""
        self.log_tab = tk.Frame(self.notebook)
        self.notebook.add(self.log_tab, text="Логи")
        self.log_text = scrolledtext.ScrolledText(self.log_tab, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def browse_file(self):
        """Загрузка Excel файла"""
        filetypes = (("Excel files", "*.xlsx *.xls"), ("All files", "*.*"))
        filename = filedialog.askopenfilename(title="Open devices list", filetypes=filetypes)
        if filename:
            self.file_path.set(filename)
            try:
                df = pd.read_excel(filename)
                if len(df.columns) < 3:
                    raise ValueError("Excel file must have at least 3 columns")

                self.ip_list = df.iloc[:, 0].dropna().astype(str).unique().tolist()
                creds = df.iloc[:, 1:3].dropna()
                self.credentials = list(set(zip(
                    creds.iloc[:, 0].astype(str),
                    creds.iloc[:, 1].astype(str)
                )))

                self.log_message(f"Загружено {len(self.ip_list)} IP-адресов и {len(self.credentials)} учетных записей")
            except Exception as e:
                self.log_message(f"Ошибка загрузки файла: {str(e)}")

    def start_execution(self):
        """Запуск выполнения команд"""
        self.commands = [entry.get() for entry in self.command_entries if entry.get().strip()]

        if not self.ip_list:
            messagebox.showerror("Ошибка", "Не загружены IP-адреса")
            return

        if not self.credentials:
            messagebox.showerror("Ошибка", "Не загружены учетные данные")
            return

        if not self.commands:
            messagebox.showerror("Ошибка", "Введите хотя бы одну команду")
            return

        self.results = {}
        self.clear_tabs()
        self.stop_event.clear()
        self.status_var.set(f"Выполнение на {len(self.ip_list)} устройствах (макс {self.max_workers} параллельно)...")

        Thread(target=self.execute_parallel).start()

    def execute_parallel(self):
        """Параллельное выполнение на устройствах"""
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self.process_device, ip): ip for ip in self.ip_list}

            for future in as_completed(futures):
                ip = futures[future]
                try:
                    future.result()
                except Exception as e:
                    self.log_message(f"Ошибка обработки {ip}: {str(e)}")

        self.log_message("\nВсе устройства обработаны!")
        success_count = sum(1 for res in self.results.values() if res['success'])
        self.status_var.set(f"Завершено. Успешно: {success_count}/{len(self.ip_list)}")

    def process_device(self, ip):
        """Обработка одного устройства (выполняется в отдельном потоке)"""
        with self.semaphore:
            if self.stop_event.is_set():
                return

            self.log_message(f"\nОбработка устройства: {ip}")
            text_widget = self.create_device_tab(ip)

            # Инициализация записи результатов для этого IP
            self.results[ip] = {
                'success': False,
                'credentials': None,
                'output': "",
                'errors': []
            }

            ssh = self.connect_to_device(ip, text_widget)
            if not ssh:
                return

            try:
                for cmd in self.commands:
                    if self.stop_event.is_set():
                        break

                    # Выполнение команды и сохранение результатов
                    command_output = self.execute_single_command(ssh, ip, cmd, text_widget)
                    self.results[ip]['output'] += f"\nКоманда: {cmd}\n{command_output}\n"

            except Exception as e:
                error_msg = f"Ошибка выполнения на {ip}: {str(e)}"
                self.results[ip]['errors'].append(error_msg)
                self.log_message(error_msg)
                self.update_device_tab(text_widget, f"\n{error_msg}\n")

            finally:
                ssh.close()
                self.log_message(f"Отключено от {ip}")

                # Помечаем как успешное, если не было ошибок
                if not self.results[ip]['errors']:
                    self.results[ip]['success'] = True

    def connect_to_device(self, ip, text_widget):
        """Подключение к устройству"""
        for user, pwd in self.credentials:
            try:
                self.log_message(f"Попытка подключения: {user}/{pwd}")
                self.update_device_tab(text_widget, f"Попытка подключения: {user}/{'*' * len(pwd)}\n")

                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(ip, username=user, password=pwd, timeout=10)

                self.log_message(f"Успешное подключение к {ip} с {user}")
                self.update_device_tab(text_widget, f"Подключено с: {user}\n\n")
                return ssh

            except Exception as e:
                error_msg = f"Ошибка подключения с {user}: {str(e)}"
                self.log_message(error_msg)
                self.update_device_tab(text_widget, f"{error_msg}\n")
                if 'ssh' in locals():
                    ssh.close()

        error_msg = f"Не удалось подключиться к {ip}"
        self.results[ip] = {'success': False, 'error': error_msg}
        self.update_device_tab(text_widget, f"\n{error_msg}\n")
        self.log_message(error_msg)
        return None

    def execute_single_command(self, ssh, ip, cmd, text_widget):
        """Выполнение одной команды с сохранением вывода"""
        self.log_message(f"Выполнение команды: {cmd}")
        self.update_device_tab(text_widget, f"Команда:\n{cmd}\n\n")

        channel = ssh.get_transport().open_session()
        channel.exec_command(cmd)
        channel.setblocking(0)

        start_time = time.time()
        output = ""

        while not self.stop_event.is_set():
            # Чтение стандартного вывода
            while channel.recv_ready():
                data = channel.recv(1024).decode('utf-8')
                output += data
                self.update_device_tab(text_widget, data)

            # Чтение вывода ошибок
            while channel.recv_stderr_ready():
                error_data = channel.recv_stderr(1024).decode('utf-8')
                output += error_data
                self.update_device_tab(text_widget, error_data)

            # Проверка завершения команды
            if channel.exit_status_ready() or (time.time() - start_time) > self.command_timeout:
                break

            time.sleep(0.1)

        # Обработка завершения команды
        exit_status = -1
        if channel.exit_status_ready():
            exit_status = channel.recv_exit_status()
            status_msg = f"\nКоманда завершена с кодом: {exit_status}\n"
        else:
            channel.close()
            status_msg = f"\nПревышено время ожидания ({self.command_timeout} сек)\n"

        self.update_device_tab(text_widget, status_msg)
        output += status_msg

        if not self.stop_event.is_set():
            time.sleep(self.delay)

        return output

    def create_device_tab(self, ip):
        """Создание вкладки для устройства"""
        if ip in self.active_tabs:
            return self.active_tabs[ip]['text']

        tab = tk.Frame(self.notebook)
        text = scrolledtext.ScrolledText(tab, wrap=tk.WORD)
        text.pack(fill=tk.BOTH, expand=True)

        self.notebook.add(tab, text=ip)
        self.notebook.select(tab)

        self.active_tabs[ip] = {'tab': tab, 'text': text}
        self.update_tab_counter()
        return text

    def update_tab_counter(self):
        """Обновление счетчика вкладок"""
        count = len(self.notebook.tabs()) - 1
        self.tab_counter.config(text=f"Устройств: {count}")

    def update_device_tab(self, text_widget, text):
        """Обновление содержимого вкладки"""
        text_widget.configure(state='normal')
        text_widget.insert(tk.END, text)
        text_widget.configure(state='disabled')
        text_widget.see(tk.END)

    def save_results(self):
        """Сохранение результатов в файл"""
        # Проверка наличия результатов
        if not self.results or all(not res['output'] for res in self.results.values()):
            messagebox.showerror("Ошибка", "Нет данных для сохранения")
            return

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"ssh_results_{timestamp}.txt"

            save_path = filedialog.asksaveasfilename(
                defaultextension=".txt",
                initialfile=filename,
                filetypes=(("Text files", "*.txt"), ("All files", "*.*"))
            )

            if save_path:
                with open(save_path, 'w', encoding='utf-8') as f:
                    # Заголовок
                    f.write("╔══════════════════════════════════╗\n")
                    f.write("║      SSH COMMANDER - RESULTS     ║\n")
                    f.write("╚══════════════════════════════════╝\n\n")

                    # Общая информация
                    f.write(f"Дата выполнения: {timestamp}\n")
                    f.write(f"Устройств обработано: {len(self.results)}\n")
                    f.write(f"Успешных подключений: {sum(1 for res in self.results.values() if res['success'])}\n\n")

                    # Выполненные команды
                    f.write("═" * 50 + "\n")
                    f.write("Выполненные команды:\n")
                    for i, cmd in enumerate(self.commands, 1):
                        f.write(f"{i}. {cmd}\n")
                    f.write("\n")

                    # Результаты по устройствам
                    for ip, result in self.results.items():
                        f.write("═" * 50 + "\n")
                        f.write(f"Устройство: {ip}\n")
                        f.write(f"Статус: {'✅ УСПЕШНО' if result['success'] else '❌ ОШИБКА'}\n")

                        if result['credentials']:
                            f.write(f"Учетные данные: {result['credentials']}\n")

                        if result['errors']:
                            f.write("\nОшибки:\n")
                            for error in result['errors']:
                                f.write(f"- {error}\n")

                        f.write("\nВывод команд:\n")
                        f.write(result['output'])
                        f.write("\n")

                self.log_message(f"Результаты сохранены в: {save_path}")
                self.status_var.set(f"Сохранено: {os.path.basename(save_path)}")

        except Exception as e:
            self.log_message(f"Ошибка сохранения: {str(e)}")
            messagebox.showerror("Ошибка", f"Не удалось сохранить файл:\n{str(e)}")

    def clear_tabs(self):
        """Очистка вкладок"""
        for ip, data in list(self.active_tabs.items()):
            self.notebook.forget(data['tab'])
            del self.active_tabs[ip]

        self.log_text.configure(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state='disabled')
        self.update_tab_counter()

    def clear_all(self):
        """Полная очистка"""
        self.clear_tabs()
        self.results = {}
        self.file_path.set("")
        self.status_var.set("Готов к работе")
        for entry in self.command_entries:
            entry.delete(0, tk.END)

    def log_message(self, message):
        """Логирование сообщений"""
        self.output_queue.put(message)

    def check_queue(self):
        """Проверка очереди сообщений"""
        while not self.output_queue.empty():
            msg = self.output_queue.get()
            self.log_text.configure(state='normal')
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.configure(state='disabled')
            self.log_text.see(tk.END)

        self.root.after(100, self.check_queue)


if __name__ == "__main__":
    root = tk.Tk()
    app = SSHClientApp(root)

    # Меню для настройки
    menu = tk.Menu(root)
    root.config(menu=menu)

    settings_menu = tk.Menu(menu, tearoff=0)
    menu.add_cascade(label="Настройки ⚙️", menu=settings_menu)

    for workers in [5, 10, 15]:
        settings_menu.add_command(
            label=f"Макс. подключений: {workers}",
            command=lambda w=workers: setattr(app, 'max_workers', w))

    root.mainloop()