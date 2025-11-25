# app.py
# Versión extendida que mantiene tu /predict intacto y agrega 15 endpoints
# Requiere: pip install flask flask-cors pymysql python-dotenv werkzeug

from flask import Flask, request, jsonify
from flask_cors import CORS
import joblib
import numpy as np
import os
import pymysql
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from dotenv import load_dotenv

# Cargar .env (crear este archivo localmente con tus credenciales)
load_dotenv()

DB_HOST = os.getenv("DB_HOST", "tu_host")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "tu_user")
DB_PASS = os.getenv("DB_PASS", "tu_pass")
DB_NAME = os.getenv("DB_NAME", "sistema_prestamos")

# Ruta de la imagen que subiste (referencia)
SCREENSHOT_PATH = "/mnt/data/bca249d3-1d00-41a1-ba36-a7a8b6e20d50.png"

app = Flask(__name__)
CORS(app)

# ---------------------------
# Carga de modelos (no tocar)
# ---------------------------
modelo = joblib.load("./models/modelo_random_forest.pkl")
modelo2 = joblib.load("./models/modelo_gradient_boosting.pkl")
modelo3 = joblib.load("./models/modelo_xgboost.pkl")

# ---------------------------
# Helpers de BD
# ---------------------------
def get_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        port=DB_PORT,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        charset="utf8mb4"
    )

def to_int_bool(v):
    """Convertir True/False/1/0/"True"/"false" a 1 o 0 (int)."""
    if v is None:
        return 0
    if isinstance(v, bool):
        return 1 if v else 0
    try:
        s = str(v).strip().lower()
        if s in ("1", "true", "t", "yes", "y"):
            return 1
        return 0
    except:
        return 0

# ---------------------------
# Tu endpoint predict (no lo toqué)
# ---------------------------
@app.route("/predict", methods=["POST"])
def predict():
    data = request.json
    print("Datos recibidos para predicción:", data)

    # Convertir a numeros (MUY IMPORTANTE)
    try:
        income = float(data["income"])
        credit_score = float(data["credit_score"])
        loan_amount = float(data["loan_amount"])
        years_employed = float(data["years_employed"])

    except Exception as e:
        return jsonify({"error": f"Datos inválidos: {e}"}), 400

    # Construir vector de características
    features = np.array([[income, credit_score, loan_amount, years_employed]])

    # Predicciones
    pred = modelo.predict(features)[0]
    pred2 = modelo2.predict(features)[0]
    pred3 = modelo3.predict(features)[0]
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            sql = """
                INSERT INTO predicciones 
                (monto, puntos, ingresos, años_empleado, resultado_rf, resultado_gb, resultado_xgb, creado_en)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            """
            cur.execute(sql, (
                loan_amount,
                credit_score,
                income,
                years_employed,
                bool(pred),
                bool(pred2),
                bool(pred3)
            ))
            registro_id = cur.lastrowid

        return jsonify({
            "ok": True,
            "registro_id": registro_id,
            "Random Forest": bool(pred),
            "Gradient Boosting": bool(pred2),
            "XGBoost": bool(pred3)
        }), 201
    except Exception as e:
        print("Error al guardar en BD:", e)
        return jsonify({"error": str(e)}), 500

# ---------------------------
# ENDPOINTS QUE AGREGUÉ
# ---------------------------

# ---------- Autenticación simple ----------
@app.route("/register", methods=["POST"])
def register():
    """
    POST /register
    JSON body: { "nombre": "Juan", "password": "secreto" }
    Response: { "ok": True, "usuario_id": 1 }
    """
    data = request.json or {}
    nombre = data.get("nombre")
    password = data.get("password")

    if not nombre or not password:
        return jsonify({"error": "nombre y password requeridos"}), 400

    try:
        conn = get_connection()
        with conn.cursor() as cur:
            sql = "INSERT INTO usuarios (nombre, password_hash) VALUES (%s, %s)"
            cur.execute(sql, (nombre, password))
            usuario_id = cur.lastrowid
        return jsonify({"ok": True, "usuario_id": usuario_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/login", methods=["POST"])
def login():


    """
    POST /login
    JSON body: { "nombre": "Juan", "password": "secreto" }
    Response: { "ok": True, "usuario_id": 1 }
    Nota: implementación simple. Devuelve usuario_id para uso por Rasa.
    """
    data = request.json or {}
    nombre = data.get("nombre")
    password = data.get("password")
    
    if not nombre or not password:
        return jsonify({"error": "nombre y password requeridos"}), 400

    try:
        conn = get_connection()
        with conn.cursor() as cur:
            # Traemos la contraseña en texto plano
            cur.execute("SELECT id, password_hash FROM usuarios WHERE nombre = %s", (nombre,))
            user = cur.fetchone()
            if not user:
                return jsonify({"error": "usuario no existe"}), 404
            if user["password_hash"] != password:
                return jsonify({"error": "password incorrecto"}), 401
            return jsonify({"ok": True, "usuario_id": user["id"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/prediction/all", methods=["GET"])
def prediction_all():
    """
    GET /prediction/all?limit=50&offset=0
    Obtiene TODAS las predicciones sin importar el usuario.
    """
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM predicciones
                ORDER BY creado_en DESC
                LIMIT %s OFFSET %s
            """, (limit, offset))

            rows = cur.fetchall()
            return jsonify(rows)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- Predicciones relacionadas (guardar y consultar) ----------
@app.route("/predict_and_save", methods=["POST"])
def predict_and_save():
    """
    POST /predict_and_save
    Body JSON: {
       "usuario_id": 1,           # opcional (puede ser null)
       "income": 3500000,
       "credit_score": 720,
       "loan_amount": 5000000,
       "years_employed": 4
    }
    Response: {
       "resultado_rf": 1,
       "resultado_gb": 0,
       "resultado_xgb": 1,
       "mensaje_rf": "aprobado",
       "mensaje_gb": "no aprobado",
       "mensaje_xgb": "aprobado",
       "prediccion_id": 123
    }
    """
    data = request.json or {}
    try:
        income = float(data["income"])
        credit_score = float(data["credit_score"])
        loan_amount = float(data["loan_amount"])
        years_employed = float(data["years_employed"])
    except Exception as e:
        return jsonify({"error": f"Datos inválidos: {e}"}), 400

    usuario_id = data.get("usuario_id")

    features = np.array([[income, credit_score, loan_amount, years_employed]])
    pred = modelo.predict(features)[0]
    pred2 = modelo2.predict(features)[0]
    pred3 = modelo3.predict(features)[0]

    rf_i = 1 if bool(pred) else 0
    gb_i = 1 if bool(pred2) else 0
    xgb_i = 1 if bool(pred3) else 0

    try:
        conn = get_connection()
        with conn.cursor() as cur:
            sql = """
            INSERT INTO predicciones (
                usuario_id, monto, puntos, ingresos, años_empleado,
                resultado_rf, resultado_gb, resultado_xgb, creado_en
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            # Nota: algunos nombres de columna tienen ñ -> se asume 'años_empleado' existe en la DB.
            cur.execute("""
                INSERT INTO predicciones (
                    usuario_id, monto, puntos, ingresos, años_empleado,
                    resultado_rf, resultado_gb, resultado_xgb, creado_en
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                usuario_id,
                int(loan_amount),
                int(credit_score),
                int(income),
                int(years_employed),
                rf_i, gb_i, xgb_i,
                datetime.utcnow()
            ))
            pred_id = cur.lastrowid
        return jsonify({
            "resultado_rf": rf_i,
            "resultado_gb": gb_i,
            "resultado_xgb": xgb_i,
            "mensaje_rf": "aprobado" if rf_i == 1 else "no aprobado",
            "mensaje_gb": "aprobado" if gb_i == 1 else "no aprobado",
            "mensaje_xgb": "aprobado" if xgb_i == 1 else "no aprobado",
            "prediccion_id": pred_id
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/prediction/latest/<int:usuario_id>", methods=["GET"])
def prediction_latest(usuario_id):
    """
    GET /prediction/latest/<usuario_id>
    Response: última predicción del usuario (si existe).
    """
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM predicciones
                WHERE usuario_id = %s
                ORDER BY creado_en DESC
                LIMIT 1
            """, (usuario_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "no hay predicciones para este usuario"}), 404
            return jsonify(row)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/prediction/history/<int:usuario_id>", methods=["GET"])
def prediction_history(usuario_id):
    """
    GET /prediction/history/<usuario_id>?limit=50&offset=0
    Response: lista de predicciones del usuario (paginable).
    """
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM predicciones
                WHERE usuario_id = %s
                ORDER BY creado_en DESC
                LIMIT %s OFFSET %s
            """, (usuario_id, limit, offset))
            rows = cur.fetchall()
            return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- Estadísticas / Reports ----------
@app.route("/stats/total", methods=["GET"])
def stats_total():
    """
    GET /stats/total
    Response: { total_predicciones: N }
    """
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM predicciones")
            total = cur.fetchone()["total"]
            return jsonify({"total_predicciones": int(total)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/stats/model_success", methods=["GET"])
def stats_model_success():
    """
    GET /stats/model_success
    Response: {
      "rf": {"aprobados": X, "rechazados": Y},
      "gb": {...},
      "xgb": {...}
    }
    """
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    SUM(resultado_rf = 1) AS rf_aprobados,
                    SUM(resultado_rf = 0) AS rf_rechazados,
                    SUM(resultado_gb = 1) AS gb_aprobados,
                    SUM(resultado_gb = 0) AS gb_rechazados,
                    SUM(resultado_xgb = 1) AS xgb_aprobados,
                    SUM(resultado_xgb = 0) AS xgb_rechazados
                FROM predicciones
            """)
            r = cur.fetchone()
            return jsonify({
                "rf": {"aprobados": int(r["rf_aprobados"] or 0), "rechazados": int(r["rf_rechazados"] or 0)},
                "gb": {"aprobados": int(r["gb_aprobados"] or 0), "rechazados": int(r["gb_rechazados"] or 0)},
                "xgb": {"aprobados": int(r["xgb_aprobados"] or 0), "rechazados": int(r["xgb_rechazados"] or 0)}
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/stats/model_comparison", methods=["GET"])
def stats_model_comparison():
    """
    GET /stats/model_comparison
    Response: {
      "todos_aprobaron": N,
      "todos_rechazaron": M,
      "coincidencia_rf_gb": X,
      ...
    }
    """
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                  SUM(resultado_rf = 1 AND resultado_gb = 1 AND resultado_xgb = 1) AS todos_aprobaron,
                  SUM(resultado_rf = 0 AND resultado_gb = 0 AND resultado_xgb = 0) AS todos_rechazaron,
                  SUM(resultado_rf = resultado_gb) AS coincidencia_rf_gb,
                  SUM(resultado_rf = resultado_xgb) AS coincidencia_rf_xgb,
                  SUM(resultado_gb = resultado_xgb) AS coincidencia_gb_xgb
                FROM predicciones
            """)
            r = cur.fetchone()
            return jsonify({k: int(r[k] or 0) for k in r})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/stats/summary", methods=["GET"])
def stats_summary():
    """
    GET /stats/summary
    Response: { total_predicciones, aprobaciones_totales, rechazadas_totales }
    """
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM predicciones")
            total = int(cur.fetchone()["total"] or 0)
            cur.execute("SELECT SUM(resultado_rf = 1 OR resultado_gb = 1 OR resultado_xgb = 1) AS aprobadas")
            aprobadas = int(cur.fetchone()["aprobadas"] or 0)
            rechazadas = total - aprobadas
            return jsonify({"total_predicciones": total, "aprobaciones_totales": aprobadas, "rechazadas_totales": rechazadas})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------------------------
# FIN - RUN
# ---------------------------
if __name__ == "__main__":
    # Host y puerto configurables via .env si quieres
    PORT = int(os.getenv("APP_PORT", 5000))
    HOST = os.getenv("APP_HOST", "0.0.0.0")
    DEBUG = os.getenv("DEBUG", "true").lower() in ("1", "true", "yes")
    app.run(debug=DEBUG, host=HOST, port=PORT)
