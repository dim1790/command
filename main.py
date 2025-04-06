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
        self.root = root
        self.root.title("Parallel SSH Commander Pro")
        self.root.geometry("1300x850")

        # Настройки выполнения
        self.max_workers = 5
        self.semaphore = Semaphore(self.max_workers)
        self.stop_event = Event()
        self.command_timeout = 15
        self.delay = 2

        # Данные
        self.ip_list = []
        self.credentials = []
        self.commands = []
        self.results = {}
        self.output_queue = Queue()
        self.active_tabs = {}

        # Инициализация интерфейса
        self.create_widgets()
        self.create_watermark()
        self.create_menu()
        self.check_queue()

    def create_watermark(self):
        """Создание водяного знака"""
        watermark = Image.new('RGBA', (300, 120), (255, 255, 255, 0))
        draw = ImageDraw.Draw(watermark)
        try:
            font = ImageFont.truetype("arial.ttf", 30)
        except:
            font = ImageFont.load_default()
        draw.text((20, 20), "FGMP1790", fill=(180, 180, 180, 80), font=font)
        self.watermark_image = ImageTk.PhotoImage(watermark)
        self.watermark_label = tk.Label(self.root, image=self.watermark_image, bd=0)
        self.watermark_label.place(relx=0.01, rely=0.97, anchor='sw')

    def create_menu(self):
        """Создание меню настроек"""
        menubar = tk.Menu(self.root)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Max connections (5)", command=lambda: self.set_max_workers(5))
        settings_menu.add_command(label="Max connections (10)", command=lambda: self.set_max_workers(10))
        settings_menu.add_command(label="Command timeout (15s)", command=lambda: self.set_timeout(15))
        settings_menu.add_command(label="Command timeout (30s)", command=lambda: self.set_timeout(30))

        menubar.add_cascade(label="Settings", menu=settings_menu)
        self.root.config(menu=menubar)

    def create_widgets(self):
        """Создание основного интерфейса"""
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Левая панель (управление)
        left_panel = tk.Frame(main_frame, width=450)
        left_panel.pack(side=tk.LEFT, fill=tk.Y)
        left_panel.pack_propagate(False)

        # Блок информации
        info_frame = tk.LabelFrame(left_panel, text="Excel File Format", padx=5, pady=5)
        info_frame.pack(fill=tk.X, padx=5, pady=5)

        info_text = """1. Column 1: Device IP addresses
2. Column 2: Login usernames
3. Column 3: Passwords

The program will try all credentials 
for each device automatically."""

        info_label = tk.Label(info_frame, text=info_text, justify=tk.LEFT, anchor='w')
        info_label.pack(fill=tk.X, padx=5, pady=5)

        # Блок загрузки файла
        file_frame = tk.LabelFrame(left_panel, text="Load Excel File", padx=5, pady=5)
        file_frame.pack(fill=tk.X, padx=5, pady=5)

        self.file_path = tk.StringVar()
        file_entry = tk.Entry(file_frame, textvariable=self.file_path, state='readonly')
        file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        browse_btn = tk.Button(file_frame, text="Browse", command=self.browse_file)
        browse_btn.pack(side=tk.RIGHT, padx=5)

        # Блок команд
        cmd_frame = tk.LabelFrame(left_panel, text="Commands to Execute", padx=5, pady=5)
        cmd_frame.pack(fill=tk.X, padx=5, pady=5)

        self.command_entries = []
        for i in range(5):
            cmd_row = tk.Frame(cmd_frame)
            cmd_row.pack(fill=tk.X, pady=2)
            tk.Label(cmd_row, text=f"Command {i + 1}:", width=10).pack(side=tk.LEFT)
            entry = tk.Entry(cmd_row)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.command_entries.append(entry)

        # Блок управления
        ctrl_frame = tk.Frame(left_panel)
        ctrl_frame.pack(fill=tk.X, padx=5, pady=10)

        exec_btn = tk.Button(ctrl_frame, text="Execute", command=self.start_execution)
        exec_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        save_btn = tk.Button(ctrl_frame, text="Save Results", command=self.save_results)
        save_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        stop_btn = tk.Button(ctrl_frame, text="Stop", command=self.stop_execution)
        stop_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # Правая панель (результаты)
        right_panel = tk.Frame(main_frame)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Вкладки с результатами
        self.notebook = ttk.Notebook(right_panel)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Вкладка логов
        self.log_tab = tk.Frame(self.notebook)
        self.notebook.add(self.log_tab, text="Execution Log")

        self.log_text = scrolledtext.ScrolledText(self.log_tab, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Статус бар
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        status_bar = tk.Label(self.root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def set_max_workers(self, num):
        """Установка максимального количества подключений"""
        self.max_workers = num
        self.semaphore = Semaphore(num)
        self.status_var.set(f"Max connections set: {num}")

    def set_timeout(self, timeout):
        """Установка таймаута выполнения команд"""
        self.command_timeout = timeout
        self.status_var.set(f"Command timeout set: {timeout} sec")

    def browse_file(self):
        """Выбор файла с устройствами"""
        filetypes = (("Excel files", "*.xlsx *.xls"), ("All files", "*.*"))
        filename = filedialog.askopenfilename(title="Select devices file", filetypes=filetypes)

        if filename:
            try:
                self.file_path.set(filename)
                df = pd.read_excel(filename)

                if len(df.columns) < 3:
                    raise ValueError("File must contain at least 3 columns")

                # Получаем уникальные IP и учетные данные
                self.ip_list = df.iloc[:, 0].dropna().astype(str).unique().tolist()
                creds = df.iloc[:, 1:3].dropna()
                self.credentials = list(set(zip(
                    creds.iloc[:, 0].astype(str),
                    creds.iloc[:, 1].astype(str)
                )))

                self.log_message(f"Loaded {len(self.ip_list)} devices and {len(self.credentials)} credentials")

            except Exception as e:
                self.log_message(f"File loading error: {str(e)}")

    def start_execution(self):
        """Запуск выполнения команд"""
        self.commands = [cmd.get() for cmd in self.command_entries if cmd.get().strip()]

        if not self.ip_list:
            messagebox.showerror("Error", "No devices loaded")
            return

        if not self.credentials:
            messagebox.showerror("Error", "No credentials loaded")
            return

        if not self.commands:
            messagebox.showerror("Error", "No commands specified")
            return

        # Подготовка к выполнению
        self.results = {}
        self.clear_tabs()
        self.stop_event.clear()

        # Запуск в отдельном потоке
        Thread(target=self.execute_parallel, daemon=True).start()
        self.status_var.set(f"Executing on {len(self.ip_list)} devices (max {self.max_workers} parallel)...")

    def stop_execution(self):
        """Остановка выполнения"""
        self.stop_event.set()
        self.status_var.set("Execution stopped by user")

    def execute_parallel(self):
        """Параллельное выполнение на устройствах"""
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self.process_device, ip): ip for ip in self.ip_list}

            for future in as_completed(futures):
                ip = futures[future]
                try:
                    future.result()
                except Exception as e:
                    self.log_message(f"Error processing {ip}: {str(e)}")

        # Завершение работы
        if not self.stop_event.is_set():
            success = sum(1 for res in self.results.values() if res['success'])
            self.status_var.set(f"Completed. Success: {success}/{len(self.ip_list)}")
        self.log_message("\nExecution finished!")

    def process_device(self, ip):
        """Обработка одного устройства"""
        with self.semaphore:
            if self.stop_event.is_set():
                return

            self.log_message(f"\nProcessing device: {ip}")
            self.create_device_tab(ip)

            # Подключение к устройству
            connected = False
            ssh = None
            used_credentials = None

            for user, pwd in self.credentials:
                try:
                    self.log_message(f"Trying credentials: {user}/{pwd}")
                    self.update_device_tab(ip, f"Trying credentials: {user}/{'*' * len(pwd)}\n")

                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh.connect(ip, username=user, password=pwd, timeout=10)
                    connected = True
                    used_credentials = f"{user}/{pwd}"
                    self.log_message(f"Connected to {ip} as {user}")
                    self.update_device_tab(ip, f"Connected as: {user}\n\n")
                    break

                except Exception as e:
                    error_msg = f"Connection failed {user}: {str(e)}"
                    self.log_message(error_msg)
                    self.update_device_tab(ip, f"{error_msg}\n")
                    if ssh:
                        ssh.close()
                    continue

            if not connected:
                error_msg = f"Failed to connect to {ip}"
                self.results[ip] = {'success': False, 'error': error_msg, 'commands': []}
                self.update_device_tab(ip, f"\n{error_msg}\n")
                return

            # Выполнение команд
            all_commands_result = []
            command_success = True

            try:
                for cmd in self.commands:
                    if self.stop_event.is_set():
                        break

                    # Выполнение одной команды
                    try:
                        self.log_message(f"Executing on {ip}: {cmd}")
                        self.update_device_tab(ip, f"Executing:\n{cmd}\n\n")

                        channel = ssh.get_transport().open_session()
                        channel.exec_command(cmd)
                        channel.setblocking(0)

                        start_time = time.time()
                        output = ""
                        error_output = ""

                        while not self.stop_event.is_set():
                            # Чтение стандартного вывода
                            while channel.recv_ready():
                                data = channel.recv(1024).decode('utf-8', 'ignore')
                                output += data
                                self.update_device_tab(ip, data)

                            # Чтение вывода ошибок
                            while channel.recv_stderr_ready():
                                data = channel.recv_stderr(1024).decode('utf-8', 'ignore')
                                error_output += data
                                self.update_device_tab(ip, data)

                            # Проверка завершения
                            if channel.exit_status_ready() or (time.time() - start_time) > self.command_timeout:
                                break

                            time.sleep(0.1)

                        # Обработка результатов команды
                        exit_status = channel.recv_exit_status() if channel.exit_status_ready() else -1

                        if (time.time() - start_time) > self.command_timeout:
                            result_msg = f"\nTimeout after {self.command_timeout} seconds\n"
                            command_success = False
                        elif exit_status != 0:
                            result_msg = f"\nFailed (status: {exit_status})\n"
                            command_success = False
                        else:
                            result_msg = f"\nCompleted successfully\n"

                        # Формируем результат команды
                        if error_output:
                            command_result = f"Command: {cmd}\nERROR:\n{error_output}{result_msg}"
                        else:
                            command_result = f"Command: {cmd}\nOUTPUT:\n{output}{result_msg}"

                        all_commands_result.append(command_result)
                        self.update_device_tab(ip, result_msg)
                        self.log_message(f"Command completed on {ip}: {cmd}")

                        if not command_success:
                            break

                    except Exception as e:
                        error_msg = f"Command failed on {ip}: {str(e)}"
                        all_commands_result.append(f"Command: {cmd}\nERROR:\n{error_msg}")
                        self.update_device_tab(ip, f"{error_msg}\n\n")
                        self.log_message(error_msg)
                        command_success = False
                        break

                    # Задержка между командами
                    time.sleep(self.delay)

                # Сохраняем результаты для устройства
                self.results[ip] = {
                    'credentials': used_credentials,
                    'commands': all_commands_result,
                    'success': command_success
                }

            finally:
                if ssh:
                    ssh.close()
                    self.log_message(f"Disconnected from {ip}")

    def update_device_tab(self, ip, text):
        """Обновление вкладки устройства"""
        if ip not in self.active_tabs:
            self.create_device_tab(ip)

        def _update():
            text_widget = self.active_tabs[ip]['text']
            text_widget.configure(state='normal')
            text_widget.insert(tk.END, text)
            text_widget.configure(state='disabled')
            text_widget.see(tk.END)

        self.root.after(0, _update)

    def create_device_tab(self, ip):
        """Создание новой вкладки для устройства"""
        if ip in self.active_tabs:
            return

        def _create():
            tab = tk.Frame(self.notebook)
            text = scrolledtext.ScrolledText(tab, wrap=tk.WORD)
            text.pack(fill=tk.BOTH, expand=True)

            text.insert(tk.END, f"Results for {ip}\n{'=' * 30}\n")
            text.configure(state='disabled')

            self.notebook.add(tab, text=ip)
            self.notebook.select(tab)

            self.active_tabs[ip] = {
                'tab': tab,
                'text': text
            }

        self.root.after(0, _create)

    def log_message(self, message):
        """Добавление сообщения в лог"""
        self.output_queue.put(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def check_queue(self):
        """Проверка очереди сообщений"""
        while not self.output_queue.empty():
            msg = self.output_queue.get()
            self.log_text.configure(state='normal')
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.configure(state='disabled')
            self.log_text.see(tk.END)

        self.root.after(100, self.check_queue)

    def save_results(self):
        """Сохранение результатов в файл"""
        if not self.results:
            messagebox.showerror("Error", "No results to save")
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
                    f.write(f"SSH Command Execution Results - {timestamp}\n\n")
                    f.write(f"Executed commands: {len(self.commands)}\n")
                    for i, cmd in enumerate(self.commands, 1):
                        f.write(f"{i}. {cmd}\n")
                    f.write("\n")

                    for ip, res in self.results.items():
                        f.write(f"{'=' * 50}\nDevice: {ip}\n")
                        f.write(f"Credentials: {res.get('credentials', 'unknown')}\n")
                        f.write(f"Status: {'SUCCESS' if res.get('success') else 'FAILED'}\n\n")

                        for cmd_result in res.get('commands', []):
                            f.write(f"{cmd_result}\n\n")

                self.log_message(f"Results saved to: {save_path}")
                self.status_var.set(f"Results saved")

        except Exception as e:
            self.log_message(f"Save error: {str(e)}")

    def clear_tabs(self):
        """Очистка всех вкладок"""
        for ip in list(self.active_tabs.keys()):
            self.notebook.forget(self.active_tabs[ip]['tab'])
            del self.active_tabs[ip]

        self.log_text.configure(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state='disabled')

    def clear_all(self):
        """Полная очистка"""
        self.clear_tabs()
        self.results = {}
        self.file_path.set("")
        self.status_var.set("Ready")
        for entry in self.command_entries:
            entry.delete(0, tk.END)


if __name__ == "__main__":
    root = tk.Tk()
    app = SSHClientApp(root)
    root.mainloop()