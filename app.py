import customtkinter as ctk
from backend.logging_config import configure_logging
from ui.app_window import App

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


if __name__ == "__main__":
    configure_logging()
    app = App()
    app.mainloop()
