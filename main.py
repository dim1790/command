import os
import time
import paramiko
import pandas as pd
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from threading import Thread
from queue import Queue
from datetime import datetime
import os
import sys

# Решение проблем с pandas при сборке
if getattr(sys, 'frozen', False):
    # Если программа запущена как собранный EXE
    os.environ['PATH'] = sys._MEIPASS + ";" + os.environ['PATH']


class SSHClientApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Advanced SSH Device Commander")
        self.root.geometry("1100x750")

        # Переменные для хранения данных
        self.ip_list = []  # Список IP-адресов из первого столбца
        self.credentials = []  # Список всех уникальных пар логин/пароль
        self.commands = []
        self.results = {}
        self.output_queue = Queue()
        self.active_tabs = {}
        self.delay = 3  # Задержка между командами в секундах

        # Создание интерфейса
        self.create_widgets()

        # Проверка очереди вывода
        self.check_queue()

    def create_widgets(self):
        # Основной контейнер
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Панель управления слева
        control_frame = tk.Frame(main_frame, width=350, relief=tk.RIDGE, borderwidth=2)
        control_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        control_frame.pack_propagate(False)

        # Фрейм для загрузки файла
        file_frame = tk.LabelFrame(control_frame, text="Device List (Excel: IPs in 1st col, creds in 2nd/3rd)", padx=5,
                                   pady=5)
        file_frame.pack(fill=tk.X, padx=5, pady=5)

        self.file_path = tk.StringVar()
        tk.Entry(file_frame, textvariable=self.file_path, state='readonly').pack(side=tk.LEFT, fill=tk.X, expand=True,
                                                                                 padx=5)
        tk.Button(file_frame, text="Browse", command=self.browse_file).pack(side=tk.RIGHT, padx=5)

        # Фрейм для ввода команд
        cmd_frame = tk.LabelFrame(control_frame, text="Commands to Execute (one after another)", padx=5, pady=5)
        cmd_frame.pack(fill=tk.X, padx=5, pady=5)

        self.command_entries = []
        for i in range(5):
            lbl = tk.Label(cmd_frame, text=f"Command {i + 1}:")
            lbl.grid(row=i, column=0, sticky=tk.W)

            entry = tk.Entry(cmd_frame)
            entry.grid(row=i, column=1, sticky=tk.EW, padx=5, pady=2)
            self.command_entries.append(entry)

        # Кнопки управления
        btn_frame = tk.Frame(control_frame)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)

        tk.Button(btn_frame, text="Execute", command=self.start_execution).pack(side=tk.LEFT, padx=5, fill=tk.X,
                                                                                expand=True)
        tk.Button(btn_frame, text="Save Results", command=self.save_results).pack(side=tk.LEFT, padx=5, fill=tk.X,
                                                                                  expand=True)
        tk.Button(btn_frame, text="Clear All", command=self.clear_all).pack(side=tk.LEFT, padx=5, fill=tk.X,
                                                                            expand=True)

        # Область вывода справа
        output_frame = tk.Frame(main_frame)
        output_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Создаем Notebook (вкладки) для вывода
        self.notebook = ttk.Notebook(output_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Добавляем начальную вкладку для логов
        self.log_tab = tk.Frame(self.notebook)
        self.notebook.add(self.log_tab, text="Log")

        self.log_text = scrolledtext.ScrolledText(self.log_tab, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Статус бар
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        status_bar = tk.Label(self.root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def browse_file(self):
        filetypes = (("Excel files", "*.xlsx *.xls"), ("All files", "*.*"))
        filename = filedialog.askopenfilename(title="Open devices list", filetypes=filetypes)
        if filename:
            self.file_path.set(filename)
            try:
                # Чтение Excel файла
                df = pd.read_excel(filename)

                # Проверяем, что есть хотя бы 3 столбца
                if len(df.columns) < 3:
                    raise ValueError("Excel file must have at least 3 columns")

                # Получаем уникальные IP из первого столбца
                self.ip_list = df.iloc[:, 0].dropna().astype(str).unique().tolist()

                # Получаем все уникальные пары логин/пароль из 2 и 3 столбцов
                creds = df.iloc[:, 1:3].dropna()
                self.credentials = list(set(zip(
                    creds.iloc[:, 0].astype(str),
                    creds.iloc[:, 1].astype(str)
                )))

                self.log_message(
                    f"Loaded {len(self.ip_list)} IP addresses and {len(self.credentials)} unique credential pairs from file.")

            except Exception as e:
                self.log_message(f"Error loading file: {str(e)}")

    def start_execution(self):
        self.commands = [entry.get() for entry in self.command_entries if entry.get().strip()]

        if not self.ip_list:
            messagebox.showerror("Error", "No IP addresses loaded")
            return

        if not self.credentials:
            messagebox.showerror("Error", "No credentials loaded")
            return

        if not self.commands:
            messagebox.showerror("Error", "Please enter at least one command")
            return

        # Очистка предыдущих результатов
        self.results = {}
        self.clear_tabs()

        # Обновление статуса
        self.status_var.set(f"Executing {len(self.commands)} commands on {len(self.ip_list)} devices...")

        # Запуск выполнения в отдельном потоке
        Thread(target=self.execute_commands, daemon=True).start()

    def execute_commands(self):
        for ip in self.ip_list:
            self.log_message(f"\nProcessing device: {ip}")
            self.create_device_tab(ip)

            # Для каждого устройства начинаем перебор учетных данных заново
            connected = False
            ssh = None
            used_credentials = None

            for user, pwd in self.credentials:
                try:
                    self.log_message(f"Trying credentials: {user}/{pwd}")
                    self.update_device_tab(ip, f"Trying credentials: {user}/{'*' * len(pwd)}\n")

                    # Создание SSH клиента
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                    # Подключение
                    ssh.connect(ip, username=user, password=pwd, timeout=10)
                    connected = True
                    used_credentials = f"{user}/{pwd}"
                    self.log_message(f"Successfully connected to {ip} with {user}")
                    self.update_device_tab(ip, f"Connected with: {user}\n\n")
                    break

                except Exception as e:
                    error_msg = f"Failed to connect with {user}: {str(e)}"
                    self.log_message(error_msg)
                    self.update_device_tab(ip, f"{error_msg}\n")
                    if ssh:
                        ssh.close()
                    continue

            if not connected:
                error_msg = f"Could not connect to {ip} with any credentials"
                self.results[ip] = error_msg
                self.update_device_tab(ip, f"\n{error_msg}\n")
                self.log_message(error_msg)
                continue

            # Выполняем команды по очереди
            all_commands_result = []
            command_success = True

            for i, cmd in enumerate(self.commands, 1):
                if not command_success:
                    break  # Прерываем выполнение если была ошибка

                try:
                    self.log_message(f"Executing command {i} on {ip}: {cmd}")
                    self.update_device_tab(ip, f"Executing command {i}:\n{cmd}\n\n")

                    # Выполнение команды
                    stdin, stdout, stderr = ssh.exec_command(cmd)

                    # Чтение вывода
                    output = stdout.read().decode().strip()
                    error = stderr.read().decode().strip()

                    # Задержка между командами
                    if i < len(self.commands):
                        time.sleep(self.delay)

                    if error:
                        result = f"Command {i} ERROR:\n{error}"
                        command_success = False
                    else:
                        result = f"Command {i} output:\n{output}"

                    # Добавляем результат
                    all_commands_result.append(result)
                    self.update_device_tab(ip, f"{result}\n\n")
                    self.log_message(f"Command {i} executed on {ip}")

                except Exception as e:
                    error_msg = f"Failed to execute command {i} on {ip}: {str(e)}"
                    all_commands_result.append(error_msg)
                    self.update_device_tab(ip, f"{error_msg}\n\n")
                    self.log_message(error_msg)
                    command_success = False

            # Сохраняем все результаты для этого устройства
            self.results[ip] = {
                'credentials': used_credentials,
                'commands': "\n".join(all_commands_result),
                'success': connected
            }

            # Закрытие соединения
            if ssh:
                ssh.close()
                self.log_message(f"Disconnected from {ip}")

        self.log_message("\nExecution completed!")
        success_count = sum(1 for res in self.results.values() if res['success'])
        self.status_var.set(f"Completed. Success: {success_count}/{len(self.ip_list)} devices.")

    def create_device_tab(self, ip, initial_text=None):
        if ip in self.active_tabs:
            return

        tab = tk.Frame(self.notebook)
        text = scrolledtext.ScrolledText(tab, wrap=tk.WORD)
        text.pack(fill=tk.BOTH, expand=True)

        if initial_text:
            text.insert(tk.END, f"Results from {ip}:\n\n")
            text.insert(tk.END, initial_text)

        text.configure(state='disabled')
        self.notebook.add(tab, text=ip)
        self.notebook.select(tab)

        self.active_tabs[ip] = {
            'tab': tab,
            'text': text
        }

    def update_device_tab(self, ip, text):
        if ip not in self.active_tabs:
            self.create_device_tab(ip)

        text_widget = self.active_tabs[ip]['text']
        text_widget.configure(state='normal')
        text_widget.insert(tk.END, text)
        text_widget.configure(state='disabled')
        text_widget.see(tk.END)

    def save_results(self):
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
                with open(save_path, 'w') as f:
                    f.write(f"SSH Command Execution Results - {timestamp}\n\n")
                    f.write(f"Executed commands:\n")
                    for i, cmd in enumerate(self.commands, 1):
                        f.write(f"{i}. {cmd}\n")
                    f.write("\nAvailable credentials:\n")
                    for user, pwd in self.credentials:
                        f.write(f"{user}/{pwd}\n")
                    f.write("\n")

                    for ip, result in self.results.items():
                        f.write(f"=== {ip} ===\n")
                        f.write(f"Status: {'SUCCESS' if result['success'] else 'FAILED'}\n")
                        if result['success']:
                            f.write(f"Credentials used: {result['credentials']}\n")
                        f.write(f"{result['commands']}\n\n")

                self.log_message(f"Results saved to {save_path}")
                self.status_var.set(f"Results saved to {os.path.basename(save_path)}")

        except Exception as e:
            self.log_message(f"Error saving results: {str(e)}")
            self.status_var.set("Error saving results")

    def clear_tabs(self):
        for ip, data in list(self.active_tabs.items()):
            self.notebook.forget(data['tab'])
            del self.active_tabs[ip]

        self.log_text.configure(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state='disabled')

    def clear_all(self):
        self.clear_tabs()
        self.results = {}
        self.status_var.set("Ready")
        for entry in self.command_entries:
            entry.delete(0, tk.END)

    def log_message(self, message):
        self.output_queue.put(message)

    def check_queue(self):
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
    root.mainloop()