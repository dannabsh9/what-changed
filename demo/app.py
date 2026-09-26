"""demo Flask app — v4 (BROKEN: divide always returns 0)."""
from flask import Flask, jsonify
import config

app = Flask(__name__)


@app.route("/")
def index():
    return jsonify({"status": "ok", "db": config.DATABASE_URL})


@app.route("/divide/<int:a>/<int:b>")
def divide(a, b):
    """Divide a by b and return the result."""
    if b == 0:
        return jsonify({"error": "division by zero"}), 400
    # BUG: integer floor-division introduced by mistake; always truncates result
    result = a // b
    return jsonify({"result": result})


if __name__ == "__main__":
    app.run(debug=config.DEBUG)
