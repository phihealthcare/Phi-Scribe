import os

from dotenv import load_dotenv

from app import create_app

load_dotenv()

app = create_app(os.environ.get("FLASK_ENV", "default"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))