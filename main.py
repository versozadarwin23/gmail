import tkinter as tk
from tkinter import messagebox, filedialog
from PIL import Image, ImageTk
import subprocess
import threading
import multiprocessing
import time
import os
import io
import customtkinter as ctk
import queue
import random
import concurrent.futures
import requests
from pathlib import Path
import re
import sys
import shutil
import tempfile

# --- App Version and Update URL ---
__version__ = "1.4.4"  # Updated version for Gmail Creator with individual Send buttons
UPDATE_URL = "https://raw.githubusercontent.com/versozadarwin23/gmail/refs/heads/main/main.py"
VERSION_CHECK_URL = "https://raw.githubusercontent.com/versozadarwin23/gmail/refs/heads/main/version.txt"

# --- Global Flag for Stopping Commands ---
is_stop_requested = threading.Event()


def run_adb_command(command, serial):
    """
    Executes a single ADB command for a specific device with a timeout, checking for a stop signal.

    Returns: (bool success, str output_or_error)
    """
    if is_stop_requested.is_set():
        # print(f"🛑 Stop signal received. Aborting command on device {serial}.")
        return False, "Stop requested."

    try:
        # Popen is used to allow non-blocking check for stop signal
        process = subprocess.Popen(['adb', '-s', serial] + command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Wait for the command to finish or for a stop signal
        timeout_seconds = 60
        start_time = time.time()
        while process.poll() is None and (time.time() - start_time < timeout_seconds):
            if is_stop_requested.is_set():
                process.terminate()  # Use terminate to kill the process
                # print(f"🛑 Terminated ADB command on device {serial}.")
                return False, "Terminated due to stop request."
            time.sleep(0.1)  # Small delay to reduce CPU usage

        if process.poll() is None:
            process.terminate()
            # Terminate the process if it timed out and raise the error
            raise subprocess.TimeoutExpired(cmd=['adb', '-s', serial] + command, timeout=timeout_seconds)

        stdout, stderr = process.communicate()

        if process.returncode != 0:
            # print(f"❌ Error executing command on device {serial}: {stderr.decode()}")
            return False, stderr.decode()
        else:
            # print(f"✅ Command executed on device {serial}: {' '.join(command)}")
            return True, stdout.decode()

    except subprocess.CalledProcessError as e:
        # print(f"❌ Error executing command on device {serial}: {e.stderr.decode()}")
        return False, e.stderr.decode()
    except FileNotFoundError:
        # print(f"❌ ADB not found. Please install it and add to PATH.")
        return False, "ADB not found. Please install it and add to PATH."
    except subprocess.TimeoutExpired:
        # print(f"❌ Command timed out on device {serial}")
        return False, "Command timed out."
    except Exception as e:
        # print(f"❌ General error on device {serial}: {e}")
        return False, str(e)


def run_text_command(text_to_send, serial):
    """
    Sends a specific text string as individual ADB text commands with a delay.
    """
    if is_stop_requested.is_set():
        # print(f"🛑 Stop signal received. Aborting text command on device {serial}.")
        return

    if not text_to_send:
        # print(f"Text is empty. Cannot send command to {serial}.")
        return

    for char in text_to_send:
        if is_stop_requested.is_set():
            # print(f"🛑 Stop signal received. Aborting text command on device {serial}.")
            return

        try:
            # Send char-by-char for better simulation fidelity, but synchronously for faster thread pool execution
            encoded_char = char.replace(' ', '%s')
            command = ['shell', 'input', 'text', encoded_char]

            # Synchronous execution of single character to avoid excessive thread submission
            subprocess.run(['adb', '-s', serial] + command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=True, timeout=5)

        except subprocess.CalledProcessError:
            # Ignore minor char errors
            pass
        except Exception as e:
            # print(f"An error occurred on device {serial}: {e}")
            break


def initiate_external_update(new_file_path, old_file_path):
    """
    Creates and executes a temporary platform-specific script (Windows batch file)
    to handle the file replacement and relaunch the application after the main
    process terminates (required for .exe self-updating).
    """
    old_file_path_str = str(old_file_path)
    new_file_path_str = str(new_file_path)

    if sys.platform.startswith('win'):
        # For Windows, create a temporary batch file in the user's temp directory
        temp_dir = tempfile.gettempdir()
        updater_script_path = os.path.join(temp_dir, f"update_{os.getpid()}_{random.randint(1000, 9999)}.bat")

        # Batch script contents:
        # 1. Wait 5 seconds for the main EXE to fully close and release the file lock.
        # 2. Move the new file over the old EXE.
        # 3. Start the newly updated EXE.
        # 4. Delete the temporary batch script itself.
        # Note: We must ensure old_file_path_str is quoted in the script
        script_content = f"""
@echo off
ECHO Waiting for ADB Commander to close...
timeout /t 5 /nobreak > NUL
ECHO Replacing file...
move /Y "{new_file_path_str}" "{old_file_path_str}"
IF NOT EXIST "{old_file_path_str}" (
    ECHO ERROR: File replacement failed!
    PAUSE
) ELSE (
    ECHO Relaunching...
    start "" "{old_file_path_str}"
)
del "%~f0"
"""
        try:
            with open(updater_script_path, 'w') as f:
                f.write(script_content)

            # Execute the batch file without waiting
            subprocess.Popen([updater_script_path], close_fds=True, creationflags=subprocess.CREATE_NEW_CONSOLE)

        except Exception as e:
            messagebox.showerror("Update Error", f"Failed to create/launch updater script: {e}")
            return

    else:
        # For Unix/Linux/macOS (Fallback to simpler move for non-Windows, but still risky for running executables)
        try:
            shutil.move(new_file_path_str, old_file_path_str)
            subprocess.Popen(['python3', old_file_path_str])
        except Exception as e:
            messagebox.showerror("Update Error", f"Failed to replace file on Unix-like system: {e}")
            return

    # Crucial step: Exit the current running process immediately
    os._exit(0)


# --- AdbControllerApp Class ---
class AdbControllerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- Configuration for Minimalist Tech Look ---
        self.title("ADB Account Automator Console")  # New Title
        # Removed fullscreen attribute. Set initial size and start zoomed/maximized.
        self.geometry("1200x800")
        self.state('zoomed')
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        # Minimalist Tech Color Palette
        self.ACCENT_COLOR = "#FFFFFF"  # Primary control accent (White/Light Gray)
        self.ACCENT_HOVER = "#A9A9A9"  # Lighter hover state
        self.DANGER_COLOR = "#FF6347"  # Tomato Red for clear warnings/stops
        self.SUCCESS_COLOR = "#00FF7F"  # Spring Green for success/install
        self.WARNING_COLOR = "#FFA500"  # Orange for power/reboot
        self.BACKGROUND_COLOR = "#181818"  # Ultra dark background
        self.FRAME_COLOR = "#2C2C2C"  # Clear separation for internal frames
        self.TEXT_COLOR = "#E0E0E0"  # Off-white text

        self.device_frames = {}
        self.device_canvases = {}
        self.device_images = {}
        self.press_start_coords = {}
        self.press_time = {}
        self.selected_device_serial = None
        self.devices = []
        self.long_press_duration = 0.5
        self.drag_threshold = 20
        self.capture_running = {}
        self.screenshot_queue = queue.Queue()
        self.capture_thread = None
        self.update_image_id = None
        self.is_capturing = False
        self.apk_path = None  # New variable for APK installation
        self.is_muted = False  # State for volume control
        self.update_check_job = None  # New attribute for scheduled check

        # Default file paths
        self.fname_file_path = r"C:\Users\user\Desktop\main\firstname.txt"
        self.lname_file_path = r"C:\Users\user\Desktop\main\lastname.txt"
        self.password_file_path = r"C:\Users\user\Desktop\main\password.txt"
        self.day_file_path = r"C:\Users\user\Desktop\main\day.txt"
        self.year_file_path = r"C:\Users\user\Desktop\main\year.txt"

        # Use a higher max_workers count as I/O operations (ADB) are often blocking
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=multiprocessing.cpu_count() * 4)

        # Main window grid configuration: 1/4 size for Control Panel, 3/4 for Device View
        self.grid_columnconfigure(0, weight=1, minsize=600)  # Control Panel (Left)
        self.grid_columnconfigure(1, weight=3)  # Device View (Right)
        self.grid_rowconfigure(0, weight=1)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # --- Control Panel Setup (Left) ---
        self.control_panel = ctk.CTkFrame(self, corner_radius=15, fg_color=self.FRAME_COLOR)
        self.control_panel.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        self.control_panel.grid_columnconfigure(0, weight=1)

        self.control_panel_scrollable = ctk.CTkScrollableFrame(self.control_panel, fg_color="transparent")
        self.control_panel_scrollable.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.control_panel_scrollable.grid_columnconfigure(0, weight=1)

        # Title - White and bold
        ctk.CTkLabel(self.control_panel_scrollable, text="ADB AUTOMATOR",
                     font=ctk.CTkFont(size=36, weight="bold"),
                     text_color=self.ACCENT_COLOR).grid(
            row=0, column=0, pady=(20, 10), sticky='ew', padx=25)

        # Separator - Distinct white line
        ctk.CTkFrame(self.control_panel_scrollable, height=2, fg_color=self.ACCENT_COLOR).grid(row=1, column=0,
                                                                                               sticky='ew',
                                                                                               padx=25, pady=15)

        # --- Device Management Section (Refreshed) ---
        device_section_frame = ctk.CTkFrame(self.control_panel_scrollable, fg_color="transparent")
        device_section_frame.grid(row=2, column=0, sticky="ew", padx=25, pady=5)
        device_section_frame.grid_columnconfigure(0, weight=1)
        device_section_frame.grid_columnconfigure(1, weight=1)

        self.device_count_label = ctk.CTkLabel(device_section_frame, text="DEVICES: 0",
                                               font=ctk.CTkFont(size=16, weight="bold"), text_color=self.TEXT_COLOR)
        self.device_count_label.grid(row=0, column=0, sticky='w', pady=(0, 5))

        self.detect_button = ctk.CTkButton(device_section_frame, text="REFRESH", command=self.detect_devices,
                                           width=120, corner_radius=8, fg_color="#3A3A3A", hover_color="#555555",
                                           font=ctk.CTkFont(size=14, weight="bold"), border_color=self.ACCENT_COLOR,
                                           border_width=1)
        self.detect_button.grid(row=0, column=1, sticky='e', pady=(0, 5))

        self.update_button = ctk.CTkButton(device_section_frame, text=f"UPDATE (v{__version__})",
                                           command=self.update_app,
                                           fg_color="#444444", hover_color="#666666", corner_radius=8,
                                           font=ctk.CTkFont(size=14, weight="bold"), height=35,
                                           text_color=self.ACCENT_COLOR)
        self.update_button.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(5, 10))

        # Tab View
        self.tab_view = ctk.CTkTabview(self.control_panel_scrollable,
                                       segmented_button_selected_color=self.ACCENT_COLOR,
                                       segmented_button_selected_hover_color=self.ACCENT_HOVER,
                                       segmented_button_unselected_hover_color="#3A3A3A",
                                       segmented_button_unselected_color=self.FRAME_COLOR,
                                       text_color=self.TEXT_COLOR,
                                       corner_radius=10,
                                       height=550)
        self.tab_view.grid(row=4, column=0, sticky="nsew", padx=25, pady=10)

        # Add tabs
        self.tab_view.add("Gmail Creator")
        self.tab_view.add("About")
        self.tab_view.set("Gmail Creator")

        self._configure_tab_layouts()

        # Status Bar
        self.status_label = ctk.CTkLabel(self.control_panel_scrollable, text="Awaiting Command...", anchor='w',
                                         font=("Consolas", 15, "italic"), text_color="#A9A9A9", height=40)
        self.status_label.grid(row=5, column=0, sticky='ew', padx=25, pady=(10, 0))

        # --- Device View Panel Setup (Right) ---
        self.device_view_panel = ctk.CTkFrame(self, fg_color=self.BACKGROUND_COLOR, corner_radius=15)
        self.device_view_panel.grid(row=0, column=1, sticky="nsew", padx=(0, 20), pady=20)
        self.device_view_panel.grid_columnconfigure(0, weight=1)
        self.device_view_panel.grid_rowconfigure(0, weight=1)

        self.stop_all_button = ctk.CTkButton(self.device_view_panel, text="TERMINATE ALL OPERATIONS",
                                             command=self.stop_all_commands, fg_color=self.DANGER_COLOR,
                                             hover_color="#CC301A", text_color=self.ACCENT_COLOR, corner_radius=10,
                                             font=ctk.CTkFont(size=18, weight="bold"), height=60)
        self.stop_all_button.pack(side="bottom", fill="x", padx=15, pady=(0, 15))

        self.detect_devices()
        self.check_for_updates()
        self.start_periodic_update_check()

    def start_periodic_update_check(self):
        """Starts a recurring, silent update check every 60 seconds (60000 ms)."""
        # 60000 milliseconds = 1 minute
        self.update_check_job = self.after(60000, self._periodic_check_updates)

    def _periodic_check_updates(self):
        """Internal method called periodically to silently check for updates."""
        threading.Thread(target=self._check_and_reschedule, daemon=True).start()

    def _check_and_reschedule(self):
        """Checks for updates and reschedules the next check."""
        try:
            response = requests.get(VERSION_CHECK_URL, timeout=10)
            response.raise_for_status()

            latest_version = response.text.strip()
            if latest_version > __version__:
                self.after(0, self.ask_for_update, latest_version)

        except requests.exceptions.RequestException:
            pass
        except Exception:
            pass
        finally:
            self.update_check_job = self.after(60000, self._periodic_check_updates)

    def check_for_updates(self):
        """
        Modified existing check_for_updates to only run once on startup
        and handle errors/messages explicitly.
        """

        def _check_in_thread():
            try:
                response = requests.get(VERSION_CHECK_URL, timeout=10)
                response.raise_for_status()

                latest_version = response.text.strip()
                if latest_version > __version__:
                    self.after(0, self.ask_for_update, latest_version)

            except requests.exceptions.HTTPError as http_err:
                status_code = http_err.response.status_code
                self.after(0, lambda: self.status_label.configure(
                    text=f"❌ ERROR: Failed to check for update. HTTP Status: {status_code}",
                    text_color=self.DANGER_COLOR))
                self.after(0, lambda: messagebox.showwarning(
                    "Update Check Failed",
                    f"Unable to reach the update server (HTTP Error {status_code}). Check your network or firewall settings."))
            except requests.exceptions.ConnectionError:
                self.after(0, lambda: self.status_label.configure(
                    text="❌ ERROR: Failed to check for update. Connection Refused.",
                    text_color=self.DANGER_COLOR))
                self.after(0, lambda: messagebox.showwarning(
                    "Update Check Failed",
                    "Cannot connect to the update server. Check your internet connection, firewall, or proxy."))
            except requests.exceptions.Timeout:
                self.after(0, lambda: self.status_label.configure(
                    text="❌ ERROR: Update download timed out.",
                    text_color=self.DANGER_COLOR))
                self.after(0, lambda: messagebox.showwarning(
                    "Update Check Failed",
                    "The connection timed out while checking for updates. Your network might be slow or unstable."))
            except requests.exceptions.RequestException as e:
                self.after(0, lambda: self.status_label.configure(
                    text=f"❌ ERROR: Update download failed. Details: {e.__class__.__name__}",
                    text_color=self.DANGER_COLOR))
                self.after(0, lambda: messagebox.showwarning(
                    "Update Download Failed",
                    f"An error occurred during download: {e.__class__.__name__}. Check logs for details."))
            except Exception:
                self.after(0, lambda: self.status_label.configure(
                    text="❌ ERROR: An unexpected error occurred during version check.",
                    text_color=self.DANGER_COLOR))
                self.after(0, lambda: messagebox.showwarning(
                    "Update Check Failed",
                    "An unexpected error occurred during the version check."))

        update_thread = threading.Thread(target=_check_in_thread, daemon=True)
        update_thread.start()

    def ask_for_update(self, latest_version):
        title = "New ADB Commander Update!"
        message = (
            f"An improved version ({latest_version}) is now available!\n\n"
            "This update contains the latest upgrades and performance improvements for faster and more reliable control of your devices.\n\n"
            "The app will close and restart to complete the update. Would you like to update now?"
        )

        response = messagebox.askyesno(title, message)
        if response:
            self.update_app()

    def on_closing(self):
        if self.update_check_job:
            self.after_cancel(self.update_check_job)

        self.stop_capture()
        self.executor.shutdown(wait=False)
        self.destroy()

    def browse_path_file(self, path_attr, entry_widget):
        """Opens a file dialog to select a data file (TXT/CSV)."""
        file_path = filedialog.askopenfilename(
            defaultextension=".txt",
            filetypes=[("Text/CSV Files", "*.txt;*.csv"), ("All Files", "*.*")]
        )
        if file_path:
            setattr(self, path_attr, file_path)
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, file_path)
            self.status_label.configure(text=f"✅ FILE SELECTED: {os.path.basename(file_path)}",
                                        text_color=self.SUCCESS_COLOR)

    def _configure_gmail_tab(self):
        """Configures the new Gmail Creator tab."""
        gmail_frame = self.tab_view.tab("Gmail Creator")
        gmail_frame.columnconfigure(0, weight=1)
        gmail_frame.rowconfigure(10, weight=1)  # Empty row for spacing

        ctk.CTkLabel(gmail_frame, text="GMAIL ACCOUNT AUTOMATION",
                     font=ctk.CTkFont(size=20, weight="bold"), text_color=self.SUCCESS_COLOR).grid(
            row=0, column=0, sticky='n', padx=15, pady=(15, 10))

        # --- WARNING/INSTRUCTION ---
        warning_box = ctk.CTkTextbox(gmail_frame, wrap="word", height=100, corner_radius=8,
                                     fg_color="#3A3A3A", text_color=self.WARNING_COLOR)
        warning_box.insert("1.0",
                           "⚠️ INSTRUCTIONS:\n1. Ensure ALL devices are on the 'Add Google Account' screen.\n2. Select separate text files for First Name, Last Name, and Password.\n3. Click 'SEND' for each data type.")
        warning_box.configure(state="disabled", font=ctk.CTkFont(family="Consolas", size=13))
        warning_box.grid(row=1, column=0, sticky='ew', padx=15, pady=(0, 15))

        # --- Data File Selection (FNAME) ---
        ctk.CTkLabel(gmail_frame, text="FIRST NAME FILE (One name per line):",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=2, column=0, sticky='w', padx=15, pady=(5, 0))

        fname_file_frame = ctk.CTkFrame(gmail_frame, fg_color="transparent")
        fname_file_frame.grid(row=3, column=0, sticky='ew', padx=15, pady=(0, 10))
        fname_file_frame.columnconfigure(0, weight=3)
        fname_file_frame.columnconfigure(1, weight=1)
        fname_file_frame.columnconfigure(2, weight=1)

        self.fname_file_path_entry = ctk.CTkEntry(fname_file_frame,
                                                  placeholder_text=os.path.basename(self.fname_file_path),
                                                  height=35, corner_radius=8)
        self.fname_file_path_entry.insert(0, self.fname_file_path)
        self.fname_file_path_entry.grid(row=0, column=0, sticky='ew', padx=(0, 5))

        browse_fname_button = ctk.CTkButton(fname_file_frame, text="BROWSE",
                                            command=lambda: self.browse_path_file('fname_file_path',
                                                                                  self.fname_file_path_entry),
                                            fg_color="#3A3A3A", hover_color="#555555", corner_radius=8, height=35)
        browse_fname_button.grid(row=0, column=1, sticky='ew', padx=(5, 5))

        send_fname_button = ctk.CTkButton(fname_file_frame, text="SEND",
                                          command=lambda: self.send_single_data('fname_file_path', 'First Name'),
                                          fg_color=self.WARNING_COLOR, hover_color="#CC8400", corner_radius=8,
                                          height=35, text_color=self.BACKGROUND_COLOR)
        send_fname_button.grid(row=0, column=2, sticky='ew', padx=(0, 0))

        # --- Data File Selection (LNAME) ---
        ctk.CTkLabel(gmail_frame, text="LAST NAME FILE (One name per line):",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=4, column=0, sticky='w', padx=15, pady=(5, 0))

        lname_file_frame = ctk.CTkFrame(gmail_frame, fg_color="transparent")
        lname_file_frame.grid(row=5, column=0, sticky='ew', padx=15, pady=(0, 10))
        lname_file_frame.columnconfigure(0, weight=3)
        lname_file_frame.columnconfigure(1, weight=1)
        lname_file_frame.columnconfigure(2, weight=1)

        self.lname_file_path_entry = ctk.CTkEntry(lname_file_frame,
                                                  placeholder_text=os.path.basename(self.lname_file_path),
                                                  height=35, corner_radius=8)
        self.lname_file_path_entry.insert(0, self.lname_file_path)
        self.lname_file_path_entry.grid(row=0, column=0, sticky='ew', padx=(0, 5))

        browse_lname_button = ctk.CTkButton(lname_file_frame, text="BROWSE",
                                            command=lambda: self.browse_path_file('lname_file_path',
                                                                                  self.lname_file_path_entry),
                                            fg_color="#3A3A3A", hover_color="#555555", corner_radius=8, height=35)
        browse_lname_button.grid(row=0, column=1, sticky='ew', padx=(5, 5))

        send_lname_button = ctk.CTkButton(lname_file_frame, text="SEND",
                                          command=lambda: self.send_single_data('lname_file_path', 'Last Name'),
                                          fg_color=self.WARNING_COLOR, hover_color="#CC8400", corner_radius=8,
                                          height=35, text_color=self.BACKGROUND_COLOR)
        send_lname_button.grid(row=0, column=2, sticky='ew', padx=(0, 0))

        # --- Data File Selection (PASSWORD) ---
        ctk.CTkLabel(gmail_frame, text="PASSWORD FILE (One password per line):",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=6, column=0, sticky='w', padx=15, pady=(5, 0))

        password_file_frame = ctk.CTkFrame(gmail_frame, fg_color="transparent")
        password_file_frame.grid(row=7, column=0, sticky='ew', padx=15, pady=(0, 20))
        password_file_frame.columnconfigure(0, weight=3)
        password_file_frame.columnconfigure(1, weight=1)
        password_file_frame.columnconfigure(2, weight=1)

        self.password_file_path_entry = ctk.CTkEntry(password_file_frame,
                                                     placeholder_text=os.path.basename(self.password_file_path),
                                                     height=35, corner_radius=8)
        self.password_file_path_entry.insert(0, self.password_file_path)
        self.password_file_path_entry.grid(row=0, column=0, sticky='ew', padx=(0, 5))

        browse_password_button = ctk.CTkButton(password_file_frame, text="BROWSE",
                                               command=lambda: self.browse_path_file('password_file_path',
                                                                                     self.password_file_path_entry),
                                               fg_color="#3A3A3A", hover_color="#555555", corner_radius=8, height=35)
        browse_password_button.grid(row=0, column=1, sticky='ew', padx=(5, 5))

        send_password_button = ctk.CTkButton(password_file_frame, text="SEND",
                                             command=lambda: self.send_single_data('password_file_path', 'Password'),
                                             fg_color=self.WARNING_COLOR, hover_color="#CC8400", corner_radius=8,
                                             height=35, text_color=self.BACKGROUND_COLOR)
        send_password_button.grid(row=0, column=2, sticky='ew', padx=(0, 0))

        # --- Birthday Day File Selection ---
        ctk.CTkLabel(gmail_frame, text="BIRTHDAY DAY FILE:",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=8, column=0, sticky='w', padx=15, pady=(5, 0))

        day_file_frame = ctk.CTkFrame(gmail_frame, fg_color="transparent")
        day_file_frame.grid(row=9, column=0, sticky='ew', padx=15, pady=(0, 10))
        day_file_frame.columnconfigure(0, weight=3)
        day_file_frame.columnconfigure(1, weight=1)
        day_file_frame.columnconfigure(2, weight=1)

        self.day_file_path_entry = ctk.CTkEntry(day_file_frame, placeholder_text=os.path.basename(self.day_file_path),
                                                height=35, corner_radius=8)
        self.day_file_path_entry.insert(0, self.day_file_path)
        self.day_file_path_entry.grid(row=0, column=0, sticky='ew', padx=(0, 5))

        browse_day_button = ctk.CTkButton(day_file_frame, text="BROWSE",
                                          command=lambda: self.browse_path_file('day_file_path',
                                                                                self.day_file_path_entry),
                                          fg_color="#3A3A3A", hover_color="#555555", corner_radius=8, height=35)
        browse_day_button.grid(row=0, column=1, sticky='ew', padx=(5, 5))

        send_day_button = ctk.CTkButton(day_file_frame, text="SEND DAY",
                                        command=lambda: self.send_single_data('day_file_path', 'Day'),
                                        fg_color=self.WARNING_COLOR, hover_color="#CC8400", corner_radius=8,
                                        height=35, text_color=self.BACKGROUND_COLOR)
        send_day_button.grid(row=0, column=2, sticky='ew', padx=(0, 0))

        # --- Birthday Year File Selection ---
        ctk.CTkLabel(gmail_frame, text="BIRTHDAY YEAR FILE:",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=10, column=0, sticky='w', padx=15, pady=(5, 0))

        year_file_frame = ctk.CTkFrame(gmail_frame, fg_color="transparent")
        year_file_frame.grid(row=11, column=0, sticky='ew', padx=15, pady=(0, 20))
        year_file_frame.columnconfigure(0, weight=3)
        year_file_frame.columnconfigure(1, weight=1)
        year_file_frame.columnconfigure(2, weight=1)

        self.year_file_path_entry = ctk.CTkEntry(year_file_frame,
                                                 placeholder_text=os.path.basename(self.year_file_path),
                                                 height=35, corner_radius=8)
        self.year_file_path_entry.insert(0, self.year_file_path)
        self.year_file_path_entry.grid(row=0, column=0, sticky='ew', padx=(0, 5))

        browse_year_button = ctk.CTkButton(year_file_frame, text="BROWSE",
                                           command=lambda: self.browse_path_file('year_file_path',
                                                                                 self.year_file_path_entry),
                                           fg_color="#3A3A3A", hover_color="#555555", corner_radius=8, height=35)
        browse_year_button.grid(row=0, column=1, sticky='ew', padx=(5, 5))

        send_year_button = ctk.CTkButton(year_file_frame, text="SEND YEAR",
                                         command=lambda: self.send_single_data('year_file_path', 'Year'),
                                         fg_color=self.WARNING_COLOR, hover_color="#CC8400", corner_radius=8,
                                         height=35, text_color=self.BACKGROUND_COLOR)
        send_year_button.grid(row=0, column=2, sticky='ew', padx=(0, 0))

    def _configure_about_tab(self):
        """Configures the new About tab with detailed information."""
        about_frame = self.tab_view.tab("About")
        about_frame.columnconfigure(0, weight=1)

        # Main Text Box for About Section
        about_text = ctk.CTkTextbox(about_frame, wrap="word", corner_radius=8, fg_color=self.FRAME_COLOR, text_color=self.TEXT_COLOR, font=ctk.CTkFont(size=16))
        about_text.pack(fill="both", expand=True, padx=20, pady=20)

        about_content = """
        About the ADB Account Automator Console

        The **ADB Account Automator Console** is a tool designed to streamline the process of creating accounts on Android devices by using ADB (Android Debug Bridge). Instead of manually typing on each device, this tool allows you to send automated commands to multiple phones at once, significantly speeding up tasks like creating Gmail accounts.

        ---
        How to Use the Tool

        1.  **Refresh and Detect Devices**: Before starting, ensure all your Android devices are connected to your computer and have USB debugging enabled. Click the "REFRESH" button to scan for and display all connected devices. Once detected, their information will appear on the right side of the interface.

        2.  **Prepare for Gmail Automation**: Navigate to the "Gmail Creator" tab. Here, you'll find fields for First Name, Last Name, Password, Birthday Day, and Birthday Year. The tool is designed to work with text files (.txt) that contain one entry per line. For example, your `firstname.txt` should contain a list of names.

        3.  **Send the Data**: Click the "BROWSE" button to select the appropriate text file for each field. After that, click the "SEND" button next to each field.
            * For **First Name, Last Name, and Password**, the tool will automatically send a unique entry from the list to each connected device and then remove those used entries from the file.
            * For **Birthday Day and Birthday Year**, the tool will also send unique entries, but it **will not** remove them from the file. This ensures that these lists can be reused for future automation.

        4.  **Execute Other ADB Commands**: The tool also includes built-in buttons for basic ADB commands like **Home**, **Back**, **Recents**, and **Screen Off**. For more advanced tasks, you can use the custom shell command feature.

        ---
        How the Program Works

        This tool operates by leveraging **Python** libraries and the **Android Debug Bridge (ADB)**.

        * **ADB Commands**: The program uses Python's `subprocess` module to execute ADB commands. These commands allow the program to "talk" to your Android device, performing actions like typing text (`adb shell input text`), pressing buttons (`adb shell input keyevent`), or swiping (`adb shell input swipe`).

        * **Threading and Concurrency**: The tool is built with multi-threading using `threading` and `concurrent.futures`. This allows it to send commands to multiple devices simultaneously, saving significant time when automating tasks across many phones.

        * **User Interface (UI)**: The user-friendly interface is built with the **CustomTkinter** library. This provides a clear, visual way for users to control their devices and send commands without needing to type them into a command prompt.

        * **File Handling**: The program reads from and updates text files. The data deletion logic is designed for one-time-use data like passwords, while data like birthdays is preserved for repeated use.

        * **Self-Updating Feature**: The tool has a built-in capability to check for and install updates. It uses the `requests` library to download a new version and creates a temporary batch file (.bat) on Windows to safely replace the old executable and relaunch itself.
        """
        about_text.insert("1.0", about_content)
        about_text.configure(state="disabled")

    def _configure_tab_layouts(self):
        """Helper method to configure the grid layout for each tab (now simplified)."""
        self._configure_gmail_tab()
        self._configure_about_tab()

    def _process_data_file(self, file_path):
        """
        Reads all lines from a file, selects a random line, and rewrites the
        file without the selected line.

        Returns: (selected_value, remaining_count) or (None, 0) on error/empty.
        """
        if not file_path or not os.path.exists(file_path):
            return None, 0

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            non_empty_lines = [line.strip() for line in lines if line.strip()]

            if not non_empty_lines:
                return None, 0

            # 1. Select random line
            random_line = random.choice(non_empty_lines)

            # 2. Filter out the used line
            used_line_stripped = random_line.strip()
            # Ensure the line is matched exactly to avoid deleting duplicates by mistake if the random choice lands on the wrong one
            try:
                # Find the index of the line to remove, based on the content of lines
                remaining_lines_with_newlines = [line for line in lines if line.strip() != used_line_stripped]

                if len(remaining_lines_with_newlines) >= len(lines):
                    messagebox.showwarning("Data Error",
                                           f"Failed to locate and remove line '{used_line_stripped}' from file {os.path.basename(file_path)}. Data not removed.")
                    return random_line, len(non_empty_lines)

            except Exception as e:
                messagebox.showerror("File Write Error", f"Pre-write failure on {os.path.basename(file_path)}: {e}")
                return random_line, len(non_empty_lines)

            # 3. Rewrite the file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(remaining_lines_with_newlines)

            return random_line, len(non_empty_lines) - 1

        except Exception as e:
            messagebox.showerror("File Operation Error",
                                 f"Failed to process data file {os.path.basename(file_path)}:\n{e}")
            return None, 0

    def send_single_data(self, path_attr, data_type):
        """
        Processes a single data file, gets a unique random
        value for EACH connected device, removes them (unless Day or Year), and sends
        each as a separate ADB input text command.
        """
        file_path = getattr(self, path_attr)
        if not file_path:
            messagebox.showwarning("Missing File", f"Please select the {data_type} file first.")
            return

        if not self.devices:
            self.status_label.configure(text="⚠️ No devices detected.", text_color="#ffc107")
            return

        # 1. Read all lines and check if there are enough for all devices
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                all_lines = [line.strip() for line in f.readlines() if line.strip()]
        except Exception as e:
            messagebox.showerror("File Read Error", f"Failed to read file {os.path.basename(file_path)}:\n{e}")
            return

        if len(all_lines) < len(self.devices):
            messagebox.showwarning("Insufficient Data",
                                   f"Not enough unique {data_type} entries available for {len(self.devices)} devices.")
            return

        # 2. Select a unique random value for EACH device
        used_values = random.sample(all_lines, len(self.devices))
        data_packets = dict(zip(self.devices, used_values))

        # 3. Send ADB command for each device with its unique data
        self.status_label.configure(text=f"[CMD] Sending unique {data_type} to each device...",
                                    text_color=self.WARNING_COLOR)

        futures = []
        for serial, value in data_packets.items():
            command = ['shell', 'input', 'text', value]
            enter_command = ['shell', 'input', 'keyevent', '66']
            # Submit tasks to the thread pool
            futures.append(self.executor.submit(run_adb_command, command, serial))
            # Chain the enter command after a short delay
            futures.append(
                self.executor.submit(lambda s, c: (time.sleep(0.5), run_adb_command(c, s)), serial, enter_command))

        # Wait for all commands to be sent
        concurrent.futures.wait(futures)

        # 4. Conditional file rewriting based on data_type
        if data_type not in ["Day", "Year"]:
            # If the data is NOT for Day or Year, remove the used lines.
            remaining_lines = [line for line in all_lines if line not in used_values]
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    for line in remaining_lines:
                        f.write(line + '\n')
                self.status_label.configure(
                    text=f"✅ {data_type.upper()} SENT. {len(used_values)} unique entries used. Remaining: {len(remaining_lines)}.",
                    text_color=self.SUCCESS_COLOR)
            except Exception as e:
                messagebox.showerror("File Write Error", f"Failed to update file {os.path.basename(file_path)}: {e}")
                self.status_label.configure(text=f"❌ {data_type.upper()} SENT but file update failed.",
                                            text_color=self.DANGER_COLOR)
                return
        else:
            # If the data type is Day or Year, do NOT rewrite the file.
            self.status_label.configure(
                text=f"✅ {data_type.upper()} SENT. {len(used_values)} entries used. File data preserved.",
                text_color=self.SUCCESS_COLOR)

    def _read_all_lines(self, file_path):
        """
        Reads all non-empty lines from a file.
        Returns: (list of lines, count)
        """
        if not file_path or not os.path.exists(file_path):
            return [], 0
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip()]
            return lines, len(lines)
        except Exception as e:
            messagebox.showerror("File Read Error", f"Failed to read file {os.path.basename(file_path)}:\n{e}")
            return [], 0

    def _remove_used_lines_from_file(self, file_path, used_lines):
        """
        Removes a set of lines from a file.
        """
        if not file_path or not os.path.exists(file_path):
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            remaining_lines = [line for line in lines if line.strip() not in used_lines]

            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(remaining_lines)
        except Exception as e:
            messagebox.showerror("File Write Error", f"Failed to update file {os.path.basename(file_path)}: {e}")

    # --- Existing Methods (Cleaned and Retained) ---

    def set_brightness(self, value):
        # ... (Implementation remains the same)
        """Sets the screen brightness via ADB settings put command (0-255)."""
        if not self.devices:
            self.status_label.configure(text="⚠️ No devices detected.", text_color="#ffc107")
            return

        # Ensure value is an integer and within the valid range
        brightness_level = int(float(value))
        if not 0 <= brightness_level <= 255:
            brightness_level = max(0, min(255, brightness_level))

        # Update slider position (useful when clicking preset buttons)
        # self.brightness_slider.set(brightness_level) # This line is commented out in the original code, but kept for reference

        self.status_label.configure(text=f"[CMD] Setting Brightness: {brightness_level} on all devices...",
                                    text_color=self.ACCENT_COLOR)

        # Set screen brightness (0-255)
        brightness_cmd = ['shell', 'settings', 'put', 'system', 'screen_brightness', str(brightness_level)]

        # Set screen brightness mode to manual (0) to allow settings to take effect
        mode_cmd = ['shell', 'settings', 'put', 'system', 'screen_brightness_mode', '0']

        for serial in self.devices:
            # Need to run both mode and brightness commands
            self.executor.submit(run_adb_command, mode_cmd, serial)
            self.executor.submit(run_adb_command, brightness_cmd, serial)

        self.status_label.configure(text=f"✅ BRIGHTNESS SET to {brightness_level}.",
                                    text_color=self.SUCCESS_COLOR)

    def toggle_mute(self):
        # ... (Implementation remains the same)
        """Toggles the volume mute state."""
        if not self.devices:
            self.status_label.configure(text="⚠️ No devices detected.", text_color="#ffc107")
            return

        keycode = '23'  # KEYCODE_MUTE (or KEYCODE_VOLUME_MUTE)

        if self.is_muted:
            # If currently muted, un-mute (send key event)
            # self.mute_button.configure(text="MUTE 🔇", fg_color="#3A3A3A", hover_color="#555555") # This line is commented out in the original code, but kept for reference
            self.status_label.configure(text="[CMD] Unmuting volume...", text_color=self.ACCENT_COLOR)
            self.is_muted = False
        else:
            # If currently unmuted, mute (send key event)
            # self.mute_button.configure(text="UNMUTE 🔊", fg_color=self.DANGER_COLOR, hover_color="#CC4028", text_color=self.ACCENT_COLOR) # This line is commented out in the original code, but kept for reference
            self.status_label.configure(text="[CMD] Muting volume...", text_color=self.ACCENT_COLOR)
            self.is_muted = True

        command = ['shell', 'input', 'keyevent', keycode]
        for serial in self.devices:
            self.executor.submit(run_adb_command, command, serial)

        self.status_label.configure(text=f"✅ Volume toggle submitted.", text_color=self.SUCCESS_COLOR)

    def reboot_devices(self):
        # ... (Implementation remains the same)
        """Reboots all connected devices."""
        if not self.devices:
            self.status_label.configure(text="⚠️ No devices detected.", text_color="#ffc107")
            return

        if not messagebox.askyesno("Confirm Action", "Are you sure you want to REBOOT all connected devices?"):
            return

        self.status_label.configure(text="[CMD] Rebooting all connected devices...", text_color=self.WARNING_COLOR)
        command = ['reboot']
        for device_serial in self.devices:
            self.executor.submit(run_adb_command, command, device_serial)

        # Redetect devices after a short delay, as rebooting devices disappear and reappear
        self.after(2000, self.detect_devices)

    def shutdown_devices(self):
        # ... (Implementation remains the same)
        """Sends a power off command to all connected devices."""
        if not self.devices:
            self.status_label.configure(text="⚠️ No devices detected.", text_color="#ffc107")
            return

        if not messagebox.askyesno("Confirm Action", "Are you sure you want to POWER OFF all connected devices?"):
            return

        self.status_label.configure(text="[CMD] Shutting down all connected devices...", text_color=self.DANGER_COLOR)
        command = ['shell', 'reboot', '-p']  # ADB command for poweroff
        for device_serial in self.devices:
            self.executor.submit(run_adb_command, command, device_serial)

        # Redetect devices to clear the list
        self.after(2000, self.detect_devices)

    def browse_apk_file(self):
        # ... (Implementation remains the same)
        """Opens a file dialog to select an APK file."""
        file_path = filedialog.askopenfilename(
            defaultextension=".apk",
            filetypes=[("APK files", "*.apk")]
        )
        if file_path:
            self.apk_path = file_path
            self.apk_path_entry.delete(0, tk.END)
            self.apk_path_entry.insert(0, os.path.basename(file_path))
            self.status_label.configure(text=f"✅ APK SELECTED: {os.path.basename(file_path)}",
                                        text_color=self.SUCCESS_COLOR)

    def install_apk_to_devices(self):
        # ... (Implementation remains the same)
        """Installs the selected APK on all connected devices."""
        if not self.apk_path or not os.path.exists(self.apk_path):
            self.status_label.configure(text="⚠️ Please select a valid APK file first.", text_color="#ffc107")
            return

        if not self.devices:
            self.status_label.configure(text="⚠️ No devices detected.", text_color="#ffc107")
            return

        self.status_label.configure(text=f"[CMD] Installing {os.path.basename(self.apk_path)} on all devices...",
                                    text_color=self.ACCENT_COLOR)

        command = ['install', '-r', self.apk_path]  # -r flag means reinstall if it already exists

        results = []

        def _install_task(serial):
            success, output = run_adb_command(command, serial)
            results.append((serial, success, output))

        # Submit tasks and wait for all to complete
        futures = [self.executor.submit(_install_task, serial) for serial in self.devices]
        concurrent.futures.wait(futures)

        # Check results and update status
        all_success = all(success for _, success, _ in results)
        if all_success:
            self.status_label.configure(text="✅ APK INSTALL SUCCESSFUL.", text_color=self.SUCCESS_COLOR)
        else:
            error_count = sum(1 for _, success, _ in results if not success)
            self.status_label.configure(text=f"❌ INSTALLATION FAILED on {error_count} device(s).",
                                        text_color=self.DANGER_COLOR)

    def run_custom_shell_command(self):
        # ... (Implementation remains the same)
        """Runs a user-defined ADB shell command on all connected devices."""
        custom_cmd_str = self.custom_cmd_entry.get().strip()
        if not custom_cmd_str:
            self.status_label.configure(text="⚠️ Please enter a shell command to run.", text_color="#ffc107")
            return

        if not self.devices:
            self.status_label.configure(text="⚠️ No devices detected.", text_color="#ffc107")
            return

        # Prepare the command: split the string into a list of arguments
        try:
            custom_args = custom_cmd_str.split()
            command = ['shell'] + custom_args

        except Exception:
            self.status_label.configure(text="❌ Invalid command format.", text_color=self.DANGER_COLOR)
            return

        self.status_label.configure(text=f"[CMD] Running custom command: '{custom_cmd_str}'",
                                    text_color=self.ACCENT_COLOR)

        for device_serial in self.devices:
            self.executor.submit(run_adb_command, command, device_serial)

        self.status_label.configure(text=f"✅ Custom command submitted to all devices.", text_color=self.SUCCESS_COLOR)

    def update_app(self):
        # ... (Implementation remains the same - uses initiate_external_update for .exe compatibility)
        # Adjusted error handling in _update_in_thread for clarity
        def _update_in_thread():
            try:
                self.status_label.configure(text="[SYS] Downloading latest version...", text_color=self.ACCENT_COLOR)

                response = requests.get(UPDATE_URL)
                response.raise_for_status()  # Raise HTTPError for bad status codes (4xx or 5xx)

                desktop_path = Path.home() / "Desktop"
                # Handle both frozen executable and script mode
                # Use sys.executable for .exe, or sys.argv[0] for script
                old_file_path = Path(sys.executable) if getattr(sys, 'frozen', False) else Path(sys.argv[0])

                # Check if we are running as a compiled executable and name the new file accordingly
                if getattr(sys, 'frozen', False):
                    # For EXE, the new file should be named the same as the old EXE (e.g., 'adb_commander.exe')
                    exe_name = old_file_path.name
                    new_file_path = Path(tempfile.gettempdir()) / f"new_{exe_name}"
                else:
                    # For script, the new file is main.py on the desktop (temporary file for download)
                    new_file_path = desktop_path / "main.py.new"

                with open(new_file_path, 'wb') as f:
                    f.write(response.content)

                messagebox.showinfo("Update Complete",
                                    "The new version has been downloaded. The application will now close and update.")

                # Use the new external update function for safe file replacement/relaunch
                initiate_external_update(new_file_path, old_file_path)

            except requests.exceptions.HTTPError as http_err:
                status_code = http_err.response.status_code
                self.after(0, lambda: self.status_label.configure(
                    text=f"❌ ERROR: Update download failed. HTTP Status: {status_code}",
                    text_color=self.DANGER_COLOR))
                self.after(0, lambda: messagebox.showerror(
                    "Update Download Failed",
                    f"Failed to download update (HTTP Error {status_code}). Check if the update file exists at the URL."))
            except requests.exceptions.ConnectionError:
                self.after(0, lambda: self.status_label.configure(
                    text="❌ ERROR: Update download failed. Connection Refused.",
                    text_color=self.DANGER_COLOR))
                self.after(0, lambda: messagebox.showerror(
                    "Update Download Failed",
                    "Failed to download update. Cannot connect to the server. Check your internet connection or firewall."))
            except requests.exceptions.Timeout:
                self.after(0, lambda: self.status_label.configure(
                    text="❌ ERROR: Update download timed out.",
                    text_color=self.DANGER_COLOR))
                self.after(0, lambda: messagebox.showerror(
                    "Update Download Failed",
                    "The connection timed out while checking for updates. Your network might be slow or unstable."))
            except requests.exceptions.RequestException as e:
                self.after(0, lambda: self.status_label.configure(
                    text=f"❌ ERROR: Update download failed. Details: {e.__class__.__name__}",
                    text_color=self.DANGER_COLOR))
                self.after(0, lambda: messagebox.showerror(
                    "Update Download Failed",
                    f"An error occurred during download: {e.__class__.__name__}. Check logs for details."))
            except Exception as e:
                self.after(0, lambda: self.status_label.configure(
                    text=f"❌ ERROR: An unexpected update error occurred: {e}",
                    text_color=self.DANGER_COLOR))
                self.after(0, lambda: messagebox.showerror(
                    "Update Error",
                    f"An unexpected file operation error occurred.\nError: {e}"))

        update_thread = threading.Thread(target=_update_in_thread, daemon=True)
        update_thread.start()

    def browse_file(self):
        # Not used in this focused version, but kept for future "Text Cmd" utility
        pass

    def _threaded_send_text(self):
        # Not used in this focused version
        pass

    def send_text_to_devices(self):
        # Not used in this focused version
        pass

    def remove_emojis_from_file(self):
        # Not used in this focused version
        pass

    def detect_devices(self):
        # ... (Implementation remains the same)
        self.stop_capture()

        for widget in self.device_view_panel.winfo_children():
            if widget != self.stop_all_button:
                widget.destroy()

        self.device_frames = {}
        self.device_canvases = {}
        self.device_images = {}
        self.press_start_coords = {}
        self.press_time = {}
        self.selected_device_serial = None
        # self.device_listbox.delete(0, tk.END) # Tinanggal ang device listbox
        self.devices = []
        self.status_label.configure(text="[SYS] Detecting devices...", text_color=self.ACCENT_COLOR)

        try:
            result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, check=True, timeout=10)
            devices_output = result.stdout.strip().split('\n')[1:]
            self.devices = [line.split('\t')[0] for line in devices_output if line.strip() and 'device' in line]
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            messagebox.showerror("Error", "ADB is not installed, not in your system PATH, or timed out.")
            self.status_label.configure(text="❌ ERROR: ADB not found or timed out.", text_color=self.DANGER_COLOR)
            self.device_count_label.configure(text="DEVICES: 0")
            return

        self.device_count_label.configure(text=f"DEVICES: {len(self.devices)}")

        if not self.devices:
            no_devices_label = ctk.CTkLabel(self.device_view_panel,
                                            text="NO DEVICES FOUND.\nEnsure USB debugging is enabled.",
                                            font=ctk.CTkFont(size=18, weight="bold"), text_color="#A9A9A9")
            no_devices_label.pack(expand=True)
            self.status_label.configure(text="⚠️ No devices detected.", text_color="#ffc107")
            return
        else:
            self.selected_device_serial = self.devices[0]  # Awtomatikong piliin ang unang device
            self.status_label.configure(
                text=f"✅ {len(self.devices)} devices connected. Showing: {self.selected_device_serial}",
                text_color=self.SUCCESS_COLOR)
            self.create_device_frame(self.selected_device_serial)
            self.start_capture_process()

    def on_device_select(self, event=None):
        pass

    def stop_capture(self):
        self.is_capturing = False
        if self.update_image_id:
            self.after_cancel(self.update_image_id)
            self.update_image_id = None
        if self.capture_thread and self.capture_thread.is_alive():
            pass
        self.screenshot_queue.queue.clear()

    def start_capture_process(self):
        if self.is_capturing:
            return

        if not self.selected_device_serial:
            return

        self.is_capturing = True
        self.capture_thread = threading.Thread(target=self.capture_screen_loop, daemon=True)
        self.capture_thread.start()
        self.update_image_id = self.after(100, self.update_image)

    def capture_screen_loop(self):
        while self.is_capturing:
            try:
                if not self.selected_device_serial:
                    self.is_capturing = False
                    break

                process = subprocess.run(['adb', '-s', self.selected_device_serial, 'exec-out', 'screencap', '-p'],
                                         capture_output=True, check=True, timeout=5)
                self.screenshot_queue.put(process.stdout)
            except subprocess.CalledProcessError as e:
                self.is_capturing = False
            except subprocess.TimeoutExpired:
                pass
            except Exception as e:
                self.is_capturing = False

            if self.is_capturing:
                time.sleep(0.05)

    def update_image(self):
        try:
            if not self.selected_device_serial or not self.is_capturing:
                return

            canvas = self.device_canvases.get(self.selected_device_serial)
            if not canvas or not canvas.winfo_exists():
                return

            if not self.screenshot_queue.empty():
                image_data = self.screenshot_queue.get()
                pil_image = Image.open(io.BytesIO(image_data))

                canvas_width = canvas.winfo_width()
                canvas_height = canvas.winfo_height()
                if canvas_width > 0 and canvas_height > 0:
                    img_width, img_height = pil_image.size
                    aspect_ratio = img_width / img_height

                    if canvas_width / canvas_height > aspect_ratio:
                        new_height = canvas_height
                        new_width = int(new_height * aspect_ratio)
                    else:
                        new_width = canvas_width
                        new_height = int(new_width / aspect_ratio)

                    if new_width > 0 and new_height > 0:
                        resized_image = pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                        tk_image = ImageTk.PhotoImage(resized_image)

                        self.device_images[self.selected_device_serial] = {'pil_image': pil_image, 'tk_image': tk_image}

                        x_pos = canvas_width / 2
                        y_pos = canvas_height / 2

                        if 'item_id' in self.device_images.get(self.selected_device_serial, {}):
                            image_item_id = self.device_images[self.selected_device_serial]['item_id']
                            canvas.coords(image_item_id, x_pos, y_pos)
                            canvas.itemconfig(image_item_id, image=tk_image)
                        else:
                            image_item_id = canvas.create_image(x_pos, y_pos, image=tk_image)
                            self.device_images[self.selected_device_serial]['item_id'] = image_item_id
                            canvas.itemconfig(image_item_id, anchor=tk.CENTER)

            if self.is_capturing:
                self.update_image_id = self.after(100, self.update_image)

        except Exception as e:
            self.stop_capture()

    def create_device_frame(self, serial):
        device_frame = ctk.CTkFrame(self.device_view_panel, fg_color=self.FRAME_COLOR, corner_radius=15)
        device_frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        self.device_frames[serial] = device_frame

        title = ctk.CTkLabel(device_frame, text=f"LIVE CONTROL: {serial}", font=ctk.CTkFont(size=18, weight="bold"),
                             text_color=self.ACCENT_COLOR)
        title.pack(pady=(15, 10))

        canvas_container = ctk.CTkFrame(device_frame, fg_color=self.BACKGROUND_COLOR, corner_radius=10)
        canvas_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=(5, 5))
        canvas_container.bind("<Configure>", self.on_canvas_container_resize)

        canvas = tk.Canvas(canvas_container, bg=self.BACKGROUND_COLOR, highlightthickness=0)
        canvas.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        self.device_canvases[serial] = canvas

        canvas.bind("<ButtonPress-1>", lambda event: self.start_press(event, serial))
        canvas.bind("<ButtonRelease-1>", lambda event: self.handle_release(event, serial))

        # Action Buttons Frame
        button_frame = ctk.CTkFrame(device_frame, fg_color="transparent")
        button_frame.pack(pady=(10, 15))

        button_style = {'corner_radius': 8, 'width': 80, 'fg_color': "#3A3A3A", 'hover_color': "#555555",
                        'text_color': self.TEXT_COLOR}

        home_button = ctk.CTkButton(button_frame, text="HOME 🏠", command=lambda: self.send_adb_keyevent(3),
                                    **button_style)
        home_button.pack(side=tk.LEFT, padx=5)

        back_button = ctk.CTkButton(button_frame, text="BACK ↩️", command=lambda: self.send_adb_keyevent(4),
                                    **button_style)
        back_button.pack(side=tk.LEFT, padx=5)

        recents_button = ctk.CTkButton(button_frame, text="RECENTS", command=lambda: self.send_adb_keyevent(187),
                                       **button_style)
        recents_button.pack(side=tk.LEFT, padx=5)

        close_button = ctk.CTkButton(button_frame, text="SCREEN OFF 💡", command=lambda: self.send_adb_keyevent(26),
                                     corner_radius=8, width=120, fg_color=self.DANGER_COLOR, hover_color="#CC4028",
                                     text_color=self.ACCENT_COLOR)
        close_button.pack(side=tk.LEFT, padx=5)

        scroll_down_button = ctk.CTkButton(button_frame, text="SCROLL DOWN",
                                           command=lambda: self.send_adb_swipe(serial, 'up'), **button_style)
        scroll_down_button.pack(side=tk.LEFT, padx=5)

        scroll_up_button = ctk.CTkButton(button_frame, text="SCROLL UP",
                                         command=lambda: self.send_adb_swipe(serial, 'down'), **button_style)
        scroll_up_button.pack(side=tk.LEFT, padx=5)

    def on_canvas_container_resize(self, event):
        if not self.selected_device_serial:
            return

        canvas = self.device_canvases.get(self.selected_device_serial)
        if not canvas:
            return

        container_width = event.width
        container_height = event.height

        aspect_ratio = 9 / 16

        if container_width / container_height > aspect_ratio:
            new_height = container_height
            new_width = int(new_height * aspect_ratio)
        else:
            new_width = container_width
            new_height = int(new_width / aspect_ratio)

        canvas.configure(width=new_width, height=new_height)
        canvas.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=new_width, height=new_height)

        self.after(10, self.update_image)

    def start_press(self, event, serial):
        self.press_time[serial] = time.time()
        self.press_start_coords[serial] = (event.x, event.y)

    def handle_release(self, event, serial):
        end_time = time.time()
        start_time = self.press_time.get(serial)

        if not start_time:
            return

        duration = end_time - start_time
        start_x, start_y = self.press_start_coords.get(serial, (event.x, event.y))
        end_x, end_y = (event.x, event.y)
        distance = ((end_x - start_x) ** 2 + (end_y - start_y) ** 2) ** 0.5

        if distance > self.drag_threshold:
            self.send_adb_swipe_command(start_x, start_y, end_x, end_y, serial)
        elif duration > self.long_press_duration:
            self.send_adb_long_press(event, serial)
        else:
            self.send_adb_tap(event, serial)

        self.press_time.pop(serial, None)
        self.press_start_coords.pop(serial, None)

    def _get_scaled_coords(self, canvas_x, canvas_y, serial):
        """Calculates ADB screen coordinates from canvas coordinates."""
        pil_image_info = self.device_images.get(self.selected_device_serial, {})
        pil_image = pil_image_info.get('pil_image')

        if not pil_image:
            return None, None

        img_width, img_height = pil_image.size
        canvas = self.device_canvases[serial]
        canvas_width = canvas.winfo_width()
        canvas_height = canvas.winfo_height()

        canvas_aspect = canvas_width / canvas_height
        image_aspect = img_width / img_height

        if canvas_aspect > image_aspect:
            effective_height = canvas_height
            effective_width = int(effective_height * image_aspect)
        else:
            new_width = canvas_width
            new_height = int(new_width / image_aspect)
            effective_width = new_width
            effective_height = new_height

        image_x_offset = (canvas_width - effective_width) // 2
        image_y_offset = (canvas_height - effective_height) // 2

        click_x = canvas_x - image_x_offset
        click_y = canvas_y - image_y_offset

        if not (0 <= click_x < effective_width and 0 <= click_y < effective_height):
            return None, None

        try:
            adb_size_output = subprocess.run(['adb', '-s', serial, 'shell', 'wm', 'size'], capture_output=True,
                                             text=True, check=True, timeout=5).stdout.strip()
            adb_width, adb_height = map(int, adb_size_output.split()[-1].split('x'))
        except Exception:
            return None, None

        scaled_x = int(click_x * adb_width / effective_width)
        scaled_y = int(click_y * adb_height / effective_height)

        return scaled_x, scaled_y

    def send_adb_tap(self, event, serial):
        scaled_x, scaled_y = self._get_scaled_coords(event.x, event.y, serial)
        if scaled_x is None:
            self.status_label.configure(text=f"⚠️ Tap ignored (outside screen area).", text_color="#ffc107")
            return

        command = ['shell', 'input', 'tap', str(scaled_x), str(scaled_y)]
        for device_serial in self.devices:
            self.executor.submit(run_adb_command, command, device_serial)
        self.status_label.configure(text=f"✅ TAP command sent.", text_color=self.SUCCESS_COLOR)

    def send_adb_long_press(self, event, serial):
        scaled_x, scaled_y = self._get_scaled_coords(event.x, event.y, serial)
        if scaled_x is None:
            self.status_label.configure(text=f"⚠️ Long press ignored (outside screen area).", text_color="#ffc107")
            return

        command = ['shell', 'input', 'swipe', str(scaled_x), str(scaled_y), str(scaled_x), str(scaled_y), '1000']
        for device_serial in self.devices:
            self.executor.submit(run_adb_command, command, device_serial)
        self.status_label.configure(text=f"✅ LONG PRESS command sent.", text_color=self.SUCCESS_COLOR)

    def send_adb_swipe_command(self, start_x, start_y, end_x, end_y, serial):
        scaled_start_x, scaled_start_y = self._get_scaled_coords(start_x, start_y, serial)
        scaled_end_x, scaled_end_y = self._get_scaled_coords(end_x, end_y, serial)

        if scaled_start_x is None or scaled_end_x is None:
            self.status_label.configure(text=f"⚠️ Swipe ignored (outside screen area).", text_color="#ffc107")
            return

        command = ['shell', 'input', 'swipe',
                   str(scaled_start_x), str(scaled_start_y),
                   str(scaled_end_x), str(scaled_end_y), '300']

        for device_serial in self.devices:
            self.executor.submit(run_adb_command, command, device_serial)
        self.status_label.configure(text=f"✅ SWIPE command sent.", text_color=self.SUCCESS_COLOR)

    def send_adb_swipe(self, serial, direction):
        try:
            adb_width_str = subprocess.run(['adb', '-s', serial, 'shell', 'wm', 'size'], capture_output=True, text=True,
                                           check=True).stdout.strip().split()[-1]
            adb_width, adb_height = map(int, adb_width_str.split('x'))

            if direction == 'down':
                start_x, start_y = adb_width // 2, adb_height // 4 * 3
                end_x, end_y = start_x, adb_height // 4
            elif direction == 'up':
                start_x, start_y = adb_width // 2, adb_height // 4
                end_x, end_y = start_x, adb_height // 4 * 3

            command = ['shell', 'input', 'swipe',
                       str(start_x), str(start_y), str(end_x), str(end_y), '300']
            for device_serial in self.devices:
                self.executor.submit(run_adb_command, command, device_serial)
            self.status_label.configure(text=f"✅ {direction.upper()} SCROLL command sent.",
                                        text_color=self.SUCCESS_COLOR)
        except Exception as e:
            self.status_label.configure(text=f"❌ ERROR: Failed to send scroll command: {e}",
                                        text_color=self.DANGER_COLOR)

    def send_adb_keyevent(self, keycode):
        command = ['shell', 'input', 'keyevent', str(keycode)]
        for device_serial in self.devices:
            self.executor.submit(run_adb_command, command, device_serial)

        key_name = {3: "HOME", 4: "BACK", 187: "RECENTS", 24: "VOL UP", 25: "VOL DOWN", 26: "POWER/SCREEN OFF"}.get(
            keycode, "KEY EVENT")
        self.status_label.configure(text=f"✅ {key_name} command sent.", text_color=self.SUCCESS_COLOR)

    def stop_all_commands(self):
        self.status_label.configure(text="⚠️ TERMINATING ALL ACTIVE COMMANDS...", text_color="#ffc107")
        is_stop_requested.set()
        self.executor.shutdown(wait=True)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=multiprocessing.cpu_count() * 4)
        is_stop_requested.clear()
        self.status_label.configure(text="✅ ALL OPERATIONS TERMINATED. Ready.", text_color=self.SUCCESS_COLOR)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    app = AdbControllerApp()
    app.mainloop()
