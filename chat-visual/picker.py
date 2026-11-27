"""Run the native directory dialog on its own GUI thread/process."""
from tkinter import Tk, filedialog


if __name__ == "__main__":
    window = Tk()
    window.withdraw()
    window.attributes("-topmost", True)
    try:
        print(filedialog.askdirectory(parent=window, title="打开 AgentTeam 项目", mustexist=True))
    finally:
        window.destroy()
