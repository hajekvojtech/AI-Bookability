"""
Flask web server for the Booking Availability Heat Map UI.

Usage: python3 app.py
Then open http://localhost:5001 in your browser.
"""
import asyncio

from flask import Flask, render_template, request, jsonify

from scrape_timeslots import scrape_timeslots, fetch_services

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/services", methods=["POST"])
def services():
    data = request.json
    url = data.get("url", "")

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        result = asyncio.run(fetch_services(url))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/scrape", methods=["POST"])
def scrape():
    data = request.json
    url = data.get("url", "")
    service = data.get("service", "")
    days = data.get("days", 30)

    if not url:
        return jsonify({"error": "No booking URL provided"}), 400
    if not service:
        return jsonify({"error": "No service name provided"}), 400

    try:
        result = asyncio.run(scrape_timeslots(url, service, days))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, port=port)
