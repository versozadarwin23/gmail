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
        
