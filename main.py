import os
import paramiko
import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from threading import Thread
from queue import Queue
from datetime import datetime


class SSHClientApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SSH Device Commander")
        self.root.geometry("800x600")

        # Переменные для хранения данных
        self.ip_list = []
        self.username = ""
        self.password = ""
        self.command = ""
        self.results = {}
        self.output_queue = Queue()

        # Создание интерфейса
        self.create_widgets()

        # Проверка очереди вывода
        self.check_queue()

    def create_widgets(self):
        # Фрейм для ввода учетных данных
        cred_frame = tk.LabelFrame(self.root, text="SSH Credentials", padx=5, pady=5)
        cred_frame.pack(fill=tk.X, padx=5, pady=5)

        tk.Label(cred_frame, text="Username:").grid(row=0, column=0, sticky=tk.W)
        self.username_entry = tk.Entry(cred_frame)
        self.username_entry.grid(row=0, column=1, sticky=tk.EW, padx=5)

        tk.Label(cred_frame, text="Password:").grid(row=1, column=0, sticky=tk.W)
        self.password_entry = tk.Entry(cred_frame, show="*")
        self.password_entry.grid(row=1, column=1, sticky=tk.EW, padx=5)

        # Фрейм для загрузки файла с IP-адресами
        file_frame = tk.LabelFrame(self.root, text="IP Address List", padx=5, pady=5)
        file_frame.pack(fill=tk.X, padx=5, pady=5)

        self.file_path = tk.StringVar()
        tk.Entry(file_frame, textvariable=self.file_path, state='readonly').pack(side=tk.LEFT, fill=tk.X, expand=True,
                                                                                 padx=5)
        tk.Button(file_frame, text="Browse", command=self.browse_file).pack(side=tk.RIGHT, padx=5)

        # Фрейм для ввода команды
        cmd_frame = tk.LabelFrame(self.root, text="Command to Execute", padx=5, pady=5)
        cmd_frame.pack(fill=tk.X, padx=5, pady=5)

        self.command_entry = tk.Entry(cmd_frame)
        self.command_entry.pack(fill=tk.X, padx=5, pady=5)

        # Кнопки управления
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)

        tk.Button(btn_frame, text="Execute", command=self.start_execution).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Save Results", command=self.save_results).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Clear", command=self.clear_output).pack(side=tk.LEFT, padx=5)

        # Вывод результатов
        output_frame = tk.LabelFrame(self.root, text="Execution Results", padx=5, pady=5)
        output_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.output_text = scrolledtext.ScrolledText(output_frame, wrap=tk.WORD)
        self.output_text.pack(fill=tk.BOTH, expand=True)

    def browse_file(self):
        filetypes = (("Excel files", "*.xlsx *.xls"), ("All files", "*.*"))
        filename = filedialog.askopenfilename(title="Open IP list", filetypes=filetypes)
        if filename:
            self.file_path.set(filename)
            try:
                df = pd.read_excel(filename)
                self.ip_list = df.iloc[:, 0].dropna().astype(str).tolist()
                self.output_queue.put(f"Loaded {len(self.ip_list)} IP addresses from file.")
            except Exception as e:
                self.output_queue.put(f"Error loading file: {str(e)}")

    def start_execution(self):
        self.username = self.username_entry.get()
        self.password = self.password_entry.get()
        self.command = self.command_entry.get()

        if not self.username or not self.password:
            messagebox.showerror("Error", "Please enter username and password")
            return

        if not self.ip_list:
            messagebox.showerror("Error", "No IP addresses loaded")
            return

        if not self.command:
            messagebox.showerror("Error", "Please enter a command to execute")
            return

        # Очистка предыдущих результатов
        self.results = {}

        # Запуск выполнения в отдельном потоке
        Thread(target=self.execute_commands, daemon=True).start()

    def execute_commands(self):
        for ip in self.ip_list:
            try:
                self.output_queue.put(f"\nConnecting to {ip}...")

                # Создание SSH клиента
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                # Подключение
                ssh.connect(ip, username=self.username, password=self.password, timeout=10)

                # Выполнение команды
                stdin, stdout, stderr = ssh.exec_command(self.command)

                # Чтение вывода
                output = stdout.read().decode().strip()
                error = stderr.read().decode().strip()

                if error:
                    self.output_queue.put(f"Error on {ip}: {error}")
                else:
                    self.output_queue.put(f"Result from {ip}:\n{output}\n")
                    self.results[ip] = output

                # Закрытие соединения
                ssh.close()

            except Exception as e:
                self.output_queue.put(f"Failed to connect/execute on {ip}: {str(e)}")
                self.results[ip] = f"Error: {str(e)}"

        self.output_queue.put("\nExecution completed!")

    def save_results(self):
        if not self.results:
            messagebox.showerror("Error", "No results to save")
            return

        try:
            # Создание имени файла с временной меткой
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"ssh_results_{timestamp}.txt"

            # Запрос места сохранения
            save_path = filedialog.asksaveasfilename(
                defaultextension=".txt",
                initialfile=filename,
                filetypes=(("Text files", "*.txt"), ("All files", "*.*"))
            )

            if save_path:
                with open(save_path, 'w') as f:
                    f.write(f"SSH Command Execution Results - {timestamp}\n\n")
                    f.write(f"Command executed: {self.command}\n\n")

                    for ip, result in self.results.items():
                        f.write(f"=== {ip} ===\n")
                        f.write(f"{result}\n\n")

                self.output_queue.put(f"Results saved to {save_path}")

        except Exception as e:
            self.output_queue.put(f"Error saving results: {str(e)}")

    def clear_output(self):
        self.output_text.delete(1.0, tk.END)

    def check_queue(self):
        while not self.output_queue.empty():
            msg = self.output_queue.get()
            self.output_text.insert(tk.END, msg + "\n")
            self.output_text.see(tk.END)
        self.root.after(100, self.check_queue)


if __name__ == "__main__":
    root = tk.Tk()
    app = SSHClientApp(root)
    root.mainloop()