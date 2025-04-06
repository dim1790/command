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

        # Настройки по умолчанию
        self.default_settings = {
            'max_workers': 5,
            'command_timeout': 10,
            'delay_between_commands': 3,
            'auto_scroll': True,
            'watermark_text': "FGMP1790"
        }
        self.current_settings = self.default_settings.copy()

        # Параметры выполнения
        self.semaphore = Semaphore(self.current_settings['max_workers'])
        self.stop_event = Event()

        # Данные программы
        self.ip_list = []
        self.credentials = []
        self.commands = []
        self.results = {}
        self.active_tabs = {}
        self.output_queue = Queue()

        # Инициализация интерфейса
        self.create_main_menu()
        self.create_widgets()
        self.create_settings_window()
        self.create_watermark()
        self.check_queue()

    def create_main_menu(self):
        """Создание главного меню программы"""
        menubar = tk.Menu(self.root)

        # Меню "Файл"
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Открыть...", command=self.browse_file)
        file_menu.add_command(label="Сохранить результаты", command=self.save_results)
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.root.quit)
        menubar.add_cascade(label="Файл", menu=file_menu)

        # Меню "Настройки"
        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Параметры...", command=self.show_settings)
        settings_menu.add_command(label="Сбросить настройки", command=self.reset_default_settings)
        menubar.add_cascade(label="Настройки", menu=settings_menu)

        # Меню "Помощь"
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="О программе", command=self.show_about)
        menubar.add_cascade(label="Помощь", menu=help_menu)

        self.root.config(menu=menubar)

    def create_widgets(self):
        """Создание основных элементов интерфейса"""
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Левая панель (управление)
        left_panel = tk.Frame(main_frame, width=400)
        left_panel.pack(side=tk.LEFT, fill=tk.Y)
        left_panel.pack_propagate(False)

        # Блок с описанием формата файла
        desc_frame = tk.LabelFrame(left_panel, text="Формат Excel-файла", padx=5, pady=5)
        desc_frame.pack(fill=tk.X, padx=5, pady=5)

        desc_text = """Excel-файл должен содержать:
1. Первый столбец - IP-адреса устройств
2. Второй столбец - логины
3. Третий столбец - пароли"""

        tk.Label(desc_frame, text=desc_text, justify=tk.LEFT).pack(padx=5, pady=5)

        # Блок загрузки файла
        file_frame = tk.LabelFrame(left_panel, text="Загрузить Excel-файл", padx=5, pady=5)
        file_frame.pack(fill=tk.X, padx=5, pady=5)

        self.file_path = tk.StringVar()
        tk.Entry(file_frame, textvariable=self.file_path, state='readonly').pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(file_frame, text="Обзор", command=self.browse_file).pack(side=tk.RIGHT)

        # Блок ввода команд
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

        # Блок кнопок управления
        btn_frame = tk.Frame(left_panel)
        btn_frame.pack(fill=tk.X, padx=5, pady=10)

        buttons = [
            ("Выполнить", self.start_execution),
            ("Остановить", self.stop_execution),
            ("Сохранить", self.save_results),
            ("Очистить", self.clear_all)
        ]

        for text, command in buttons:
            tk.Button(btn_frame, text=text, command=command).pack(
                side=tk.LEFT, expand=True, padx=2)

        # Правая панель (результаты)
        right_panel = tk.Frame(main_frame)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Notebook для вкладок
        self.notebook = ttk.Notebook(right_panel)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Вкладка для логов
        self.create_log_tab()

        # Статус бар
        self.status_var = tk.StringVar()
        self.status_var.set("Готов к работе")
        status_bar = tk.Label(self.root, textvariable=self.status_var,
                              bd=1, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Счетчик устройств
        self.tab_counter = tk.Label(self.root, text="Устройств: 0",
                                    bd=1, relief=tk.SUNKEN)
        self.tab_counter.pack(side=tk.BOTTOM, fill=tk.X)

    def create_settings_window(self):
        """Создание окна настроек"""
        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title("Настройки программы")
        self.settings_window.withdraw()

        # Максимальное количество потоков
        tk.Label(self.settings_window, text="Макс. потоков:").grid(row=0, column=0, sticky='e')
        self.max_workers_var = tk.IntVar(value=self.current_settings['max_workers'])
        tk.Spinbox(self.settings_window, from_=1, to=20, textvariable=self.max_workers_var).grid(row=0, column=1)

        # Таймаут выполнения команд
        tk.Label(self.settings_window, text="Таймаут (сек):").grid(row=1, column=0, sticky='e')
        self.timeout_var = tk.IntVar(value=self.current_settings['command_timeout'])
        tk.Spinbox(self.settings_window, from_=1, to=60, textvariable=self.timeout_var).grid(row=1, column=1)

        # Задержка между командами
        tk.Label(self.settings_window, text="Задержка (сек):").grid(row=2, column=0, sticky='e')
        self.delay_var = tk.IntVar(value=self.current_settings['delay_between_commands'])
        tk.Spinbox(self.settings_window, from_=0, to=10, textvariable=self.delay_var).grid(row=2, column=1)

        # Автопрокрутка
        self.auto_scroll_var = tk.BooleanVar(value=self.current_settings['auto_scroll'])
        tk.Checkbutton(self.settings_window, text="Автопрокрутка", variable=self.auto_scroll_var).grid(row=3,
                                                                                                       columnspan=2)

        # Водяной знак
        tk.Label(self.settings_window, text="Водяной знак:").grid(row=4, column=0, sticky='e')
        self.watermark_var = tk.StringVar(value=self.current_settings['watermark_text'])
        tk.Entry(self.settings_window, textvariable=self.watermark_var).grid(row=4, column=1)

        # Кнопки
        tk.Button(self.settings_window, text="Применить", command=self.apply_settings).grid(row=5, column=0, pady=10)
        tk.Button(self.settings_window, text="По умолчанию", command=self.reset_default_settings).grid(row=5, column=1)

    def apply_settings(self):
        """Применение измененных настроек"""
        self.current_settings = {
            'max_workers': self.max_workers_var.get(),
            'command_timeout': self.timeout_var.get(),
            'delay_between_commands': self.delay_var.get(),
            'auto_scroll': self.auto_scroll_var.get(),
            'watermark_text': self.watermark_var.get()
        }
        self.semaphore = Semaphore(self.current_settings['max_workers'])
        self.create_watermark()
        self.settings_window.withdraw()
        self.log_message("Настройки успешно применены")

    def reset_default_settings(self):
        """Сброс настроек к значениям по умолчанию"""
        self.max_workers_var.set(self.default_settings['max_workers'])
        self.timeout_var.set(self.default_settings['command_timeout'])
        self.delay_var.set(self.default_settings['delay_between_commands'])
        self.auto_scroll_var.set(self.default_settings['auto_scroll'])
        self.watermark_var.set(self.default_settings['watermark_text'])
        self.log_message("Настройки сброшены к значениям по умолчанию")

    def show_settings(self):
        """Отображение окна настроек"""
        self.settings_window.deiconify()
        self.settings_window.lift()

    def show_about(self):
        """Отображение информации о программе"""
        about_window = tk.Toplevel(self.root)
        about_window.title("О программе")
        tk.Label(about_window, text="Parallel SSH Commander\nВерсия 1.0").pack(pady=10)
        tk.Button(about_window, text="OK", command=about_window.destroy).pack(pady=10)

    def create_log_tab(self):
        """Создание вкладки для системных логов"""
        self.log_tab = tk.Frame(self.notebook)
        self.notebook.add(self.log_tab, text="Логи")
        self.log_text = scrolledtext.ScrolledText(self.log_tab, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def create_watermark(self):
        """Создание водяного знака"""
        try:
            watermark = Image.new('RGBA', (250, 100), (255, 255, 255, 0))
            draw = ImageDraw.Draw(watermark)
            font = ImageFont.truetype("arial.ttf", 24)
            draw.text((10, 10), self.current_settings['watermark_text'],
                      fill=(150, 150, 150, 100), font=font)
            self.watermark_image = ImageTk.PhotoImage(watermark)
            if hasattr(self, 'watermark_label'):
                self.watermark_label.config(image=self.watermark_image)
            else:
                self.watermark_label = tk.Label(self.root, image=self.watermark_image, bd=0)
                self.watermark_label.place(relx=0.01, rely=0.98, anchor='sw')
        except Exception as e:
            print(f"Ошибка создания водяного знака: {e}")

    def browse_file(self):
        """Выбор и загрузка Excel-файла с устройствами"""
        filetypes = (("Excel files", "*.xlsx *.xls"), ("All files", "*.*"))
        filename = filedialog.askopenfilename(title="Выберите файл с устройствами", filetypes=filetypes)
        if filename:
            self.file_path.set(filename)
            try:
                df = pd.read_excel(filename)
                if len(df.columns) < 3:
                    raise ValueError("Файл должен содержать минимум 3 столбца")

                # Получаем уникальные IP-адреса
                self.ip_list = df.iloc[:, 0].dropna().astype(str).unique().tolist()

                # Получаем уникальные пары логин/пароль
                creds = df.iloc[:, 1:3].dropna()
                self.credentials = list(set(zip(
                    creds.iloc[:, 0].astype(str),
                    creds.iloc[:, 1].astype(str)
                )))

                self.log_message(f"Загружено {len(self.ip_list)} устройств и {len(self.credentials)} учетных записей")
                self.tab_counter.config(text=f"Устройств: {len(self.ip_list)}")

            except Exception as e:
                self.log_message(f"Ошибка загрузки файла: {str(e)}")
                messagebox.showerror("Ошибка", f"Не удалось загрузить файл:\n{str(e)}")

    def start_execution(self):
        """Запуск выполнения команд на устройствах"""
        # Получаем команды из полей ввода
        self.commands = [entry.get() for entry in self.command_entries if entry.get().strip()]

        # Проверяем наличие необходимых данных
        if not self.ip_list:
            messagebox.showerror("Ошибка", "Не загружены устройства")
            return
        if not self.credentials:
            messagebox.showerror("Ошибка", "Не загружены учетные данные")
            return
        if not self.commands:
            messagebox.showerror("Ошибка", "Не указаны команды для выполнения")
            return

        # Очищаем предыдущие результаты
        self.results = {}
        self.clear_tabs(keep_logs=True)
        self.stop_event.clear()

        # Обновляем статус
        self.status_var.set(f"Выполнение на {len(self.ip_list)} устройствах...")

        # Запускаем выполнение в отдельном потоке
        Thread(target=self.execute_parallel, daemon=True).start()

    def stop_execution(self):
        """Остановка выполнения команд"""
        self.stop_event.set()
        self.status_var.set("Выполнение остановлено")

    def execute_parallel(self):
        """Параллельное выполнение команд на устройствах"""
        with ThreadPoolExecutor(max_workers=self.current_settings['max_workers']) as executor:
            # Создаем future для каждого устройства
            futures = {executor.submit(self.process_device, ip): ip for ip in self.ip_list}

            # Обрабатываем результаты по мере завершения
            for future in as_completed(futures):
                ip = futures[future]
                try:
                    future.result()  # Получаем результат или исключение
                except Exception as e:
                    self.log_message(f"Ошибка обработки устройства {ip}: {str(e)}")

        # Обновляем статус после завершения
        success_count = sum(1 for res in self.results.values() if res['success'])
        self.status_var.set(f"Завершено. Успешно: {success_count}/{len(self.ip_list)}")
        self.log_message("\nВыполнение завершено")

    def process_device(self, ip):
        """Обработка одного устройства"""
        with self.semaphore:
            if self.stop_event.is_set():
                return

            self.log_message(f"\nОбработка устройства: {ip}")
            text_widget = self.create_device_tab(ip)

            # Инициализация записи результатов
            self.results[ip] = {
                'success': False,
                'credentials': None,
                'output': "",
                'errors': []
            }

            # Подключение к устройству
            ssh = self.connect_to_device(ip, text_widget)
            if not ssh:
                return

            try:
                # Выполнение всех команд на устройстве
                for cmd in self.commands:
                    if self.stop_event.is_set():
                        break

                    # Выполняем команду и сохраняем вывод
                    command_output = self.execute_single_command(ssh, ip, cmd, text_widget)
                    self.results[ip]['output'] += f"\nКоманда: {cmd}\n{command_output}\n"

            except Exception as e:
                error_msg = f"Ошибка выполнения на {ip}: {str(e)}"
                self.results[ip]['errors'].append(error_msg)
                self.log_message(error_msg)
                self.update_device_tab(text_widget, f"\n{error_msg}\n")

            finally:
                # Закрываем соединение
                ssh.close()
                self.log_message(f"Отключено от {ip}")

                # Помечаем как успешное, если не было ошибок
                if not self.results[ip]['errors']:
                    self.results[ip]['success'] = True

    def connect_to_device(self, ip, text_widget):
        """Подключение к устройству с перебором учетных данных"""
        for user, pwd in self.credentials:
            try:
                self.log_message(f"Попытка подключения: {user}/{pwd}")
                self.update_device_tab(text_widget, f"Попытка подключения: {user}/{'*' * len(pwd)}\n")

                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(ip, username=user, password=pwd, timeout=10)

                self.log_message(f"Успешное подключение к {ip} с {user}")
                self.update_device_tab(text_widget, f"Подключено с: {user}\n\n")

                # Сохраняем использованные учетные данные
                self.results[ip]['credentials'] = f"{user}/{pwd}"
                return ssh

            except Exception as e:
                error_msg = f"Ошибка подключения с {user}: {str(e)}"
                self.results[ip]['errors'].append(error_msg)
                self.log_message(error_msg)
                self.update_device_tab(text_widget, f"{error_msg}\n")
                if 'ssh' in locals():
                    ssh.close()

        error_msg = f"Не удалось подключиться к {ip}"
        self.results[ip]['errors'].append(error_msg)
        self.update_device_tab(text_widget, f"\n{error_msg}\n")
        self.log_message(error_msg)
        return None

    def execute_single_command(self, ssh, ip, cmd, text_widget):
        """Выполнение одной команды на устройстве"""
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
            if channel.exit_status_ready() or (time.time() - start_time) > self.current_settings['command_timeout']:
                break

            time.sleep(0.1)

        # Обработка завершения команды
        exit_status = -1
        if channel.exit_status_ready():
            exit_status = channel.recv_exit_status()
            status_msg = f"\nКоманда завершена с кодом: {exit_status}\n"
        else:
            channel.close()
            status_msg = f"\nПревышено время ожидания ({self.current_settings['command_timeout']} сек)\n"

        self.update_device_tab(text_widget, status_msg)
        output += status_msg

        # Задержка между командами, если не была нажата остановка
        if not self.stop_event.is_set():
            time.sleep(self.current_settings['delay_between_commands'])

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
        """Обновление счетчика устройств"""
        count = len(self.notebook.tabs()) - 1  # Исключаем вкладку логов
        self.tab_counter.config(text=f"Устройств: {count}")

    def update_device_tab(self, text_widget, text):
        """Обновление содержимого вкладки устройства"""
        text_widget.configure(state='normal')
        text_widget.insert(tk.END, text)
        if self.current_settings['auto_scroll']:
            text_widget.see(tk.END)
        text_widget.configure(state='disabled')

    def save_results(self):
        """Сохранение результатов выполнения в файл"""
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
                    # Заголовок отчета
                    f.write("=" * 60 + "\n")
                    f.write(f"Parallel SSH Commander - Отчет\n")
                    f.write(f"Дата создания: {timestamp}\n")
                    f.write("=" * 60 + "\n\n")

                    # Общая информация
                    success_count = sum(1 for res in self.results.values() if res['success'])
                    f.write(f"Всего устройств: {len(self.results)}\n")
                    f.write(f"Успешных подключений: {success_count}\n")
                    f.write(f"Ошибок подключения: {len(self.results) - success_count}\n\n")

                    # Выполненные команды
                    f.write("Выполненные команды:\n")
                    for i, cmd in enumerate(self.commands, 1):
                        f.write(f"{i}. {cmd}\n")
                    f.write("\n")

                    # Результаты по устройствам
                    for ip, result in self.results.items():
                        f.write("-" * 60 + "\n")
                        f.write(f"Устройство: {ip}\n")
                        f.write(f"Статус: {'УСПЕШНО' if result['success'] else 'ОШИБКА'}\n")

                        if result['credentials']:
                            f.write(f"Учетные данные: {result['credentials']}\n")

                        if result['errors']:
                            f.write("\nОшибки:\n")
                            for error in result['errors']:
                                f.write(f"• {error}\n")

                        f.write("\nВывод команд:\n")
                        f.write(result['output'])
                        f.write("\n")

                self.log_message(f"Результаты сохранены в файл: {save_path}")
                self.status_var.set(f"Сохранено: {os.path.basename(save_path)}")

        except Exception as e:
            self.log_message(f"Ошибка сохранения: {str(e)}")
            messagebox.showerror("Ошибка", f"Не удалось сохранить файл:\n{str(e)}")

    def clear_all(self):
        """Полная очистка программы"""
        self.stop_execution()
        self.clear_tabs()
        self.results = {}
        self.file_path.set("")
        for entry in self.command_entries:
            entry.delete(0, tk.END)
        self.status_var.set("Готов к работе")

    def clear_tabs(self, keep_logs=False):
        """Очистка вкладок устройств"""
        tabs_to_remove = list(self.active_tabs.keys())
        for ip in tabs_to_remove:
            self.notebook.forget(self.active_tabs[ip]['tab'])
            del self.active_tabs[ip]

        if not keep_logs:
            self.log_text.configure(state='normal')
            self.log_text.delete(1.0, tk.END)
            self.log_text.configure(state='disabled')

        self.update_tab_counter()

    def log_message(self, message):
        """Добавление сообщения в лог"""
        self.output_queue.put(message)

    def check_queue(self):
        """Проверка очереди сообщений и вывод в лог"""
        while not self.output_queue.empty():
            msg = self.output_queue.get()
            self.log_text.configure(state='normal')
            self.log_text.insert(tk.END, msg + "\n")
            if self.current_settings['auto_scroll']:
                self.log_text.see(tk.END)
            self.log_text.configure(state='disabled')

        self.root.after(100, self.check_queue)


if __name__ == "__main__":
    root = tk.Tk()
    app = SSHClientApp(root)
    root.mainloop()