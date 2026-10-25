import os
import sys
import webview

class Api:
    def get_system_data(self):
        return {"status": "success", "message": "Данные успешно получены из Python!"}

def get_resource_path(relative_path):
    """ Получает абсолютный путь к ресурсам, совместимый с PyInstaller """
    if hasattr(sys, '_MEIPASS'):
        # Путь внутри временной папки собранного .exe/.app
        return os.path.join(sys._MEIPASS, relative_path)
    # Путь при обычной разработке
    return os.path.join(os.path.dirname(__file__), relative_path)

def main():
    api = Api()
    
    # 🔴 ПЕРЕД СБОРКОЙ СТАВИМ FALSE
    DEV_MODE = True 

    if DEV_MODE:
        url = 'http://localhost:5173'
    else:
        # Указываем путь к папке dist через функцию проверки путей
        url = get_resource_path('frontend/dist/index.html')

    webview.create_window(
        title='EyeDoc',
        url=url,
        js_api=api,
        width=1000,
        height=700
    )
    webview.start(debug=DEV_MODE)

if __name__ == '__main__':
    main()
