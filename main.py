import os
import requests
from datetime import datetime

from flask import Flask, request, jsonify

import sheets_manager as db
from parser import parsear_gasto, parsear_ingreso, parsear_monto, es_ahorro, es_ingreso, buscar_cuenta

app = Flask(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
CRON_SECRET = os.environ.get("CRON_SECRET", "cambiame")

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def enviar_mensaje(texto, chat_id=None):
    requests.post(f"{API_URL}/sendMessage", json={
        "chat_id": chat_id or CHAT_ID,
        "text": texto,
        "parse_mode": "HTML",
    })


# ---------- Comandos ----------

def cmd_help():
    return (
        "Te entiendo si me escribís en texto libre, por ejemplo:\n"
        "<i>gaste 500 en comida</i> (cuenta Efectivo por default)\n"
        "<i>gaste 500 en comida con galicia</i>\n"
        "<i>cobre 300000 en mercado pago</i>\n"
        "<i>ahorre 5000</i>\n\n"
        "Cuentas que reconozco: efectivo, galicia, mercado pago, wallbit, cuenta dni\n\n"
        "Comandos:\n"
        "/resumen — total gastado, ingreso, ahorro y categorías del mes\n"
        "/saldos — cuánto tenés en cada cuenta y lo invertido\n"
        "/invertir Monto — suma plata a tu saldo invertido\n"
        "/rendimiento Monto — anota lo que rindió lo invertido este mes\n"
        "/pendiente Descripcion - Monto - DD/MM/AAAA — algo que tenés que pagar\n"
        "/pendientes — lista lo que falta pagar\n"
        "/pagado ID — marca un pendiente como pagado\n"
        "/planilla — te mando el link a la planilla de Google Sheets\n\n"
        "¿Te equivocaste en el último gasto?\n"
        "/corregir cuenta galicia — le cambia la cuenta\n"
        "/corregir monto 1500 — le cambia el monto\n"
        "/corregir categoria super — le cambia la categoría\n"
        "/deshacer — lo borra directamente\n"
    )


def cmd_resumen():
    total_gastado, ingreso, ahorro_sobrante, ahorro_manual, ahorro_total, por_categoria = db.resumen_mes_actual()
    lineas = [
        f"<b>Total gastado: ${total_gastado:,.2f}</b>",
        f"Ingreso del mes: ${ingreso:,.2f}",
        f"Ahorro (sobrante): ${ahorro_sobrante:,.2f}",
        f"Ahorro manual: ${ahorro_manual:,.2f}",
        f"<b>Ahorro total: ${ahorro_total:,.2f}</b>",
        "",
    ]
    if por_categoria:
        lineas.append("Por categoría:")
        for cat, monto in por_categoria:
            lineas.append(f"• {cat}: ${monto:,.2f}")
    return "\n".join(lineas)


def cmd_saldos():
    saldos = db.obtener_saldos()
    lineas = ["<b>Saldos:</b>"]
    for cuenta, saldo in saldos:
        lineas.append(f"• {cuenta}: ${saldo:,.2f}")
    rendimiento = db.rendimiento_mes_actual()
    if rendimiento:
        lineas.append(f"\nRendimiento cargado este mes: ${rendimiento:,.2f}")
    return "\n".join(lineas)


def cmd_invertir(texto_args):
    monto = parsear_monto(texto_args)
    if monto is None:
        return "Usá: /invertir 5000"
    db.invertir(monto)
    return f"Sumado ${monto:,.2f} a Invertido."


def cmd_rendimiento(texto_args):
    monto = parsear_monto(texto_args)
    if monto is None:
        return "Usá: /rendimiento 8000"
    db.registrar_rendimiento(monto)
    return f"Anotado: este mes lo invertido rindió ${monto:,.2f}."


def cmd_pendiente(texto_args):
    partes = [p.strip() for p in texto_args.split(" - ")]
    if len(partes) != 3:
        return ("Formato: /pendiente Descripcion - Monto - DD/MM/AAAA\n"
                "Ejemplo: /pendiente Alquiler - 50000 - 10/09/2026")
    descripcion, monto_str, fecha_str = partes
    try:
        monto = float(monto_str.replace(",", "."))
        fecha = datetime.strptime(fecha_str, "%d/%m/%Y").date()
    except ValueError:
        return "No pude leer el monto o la fecha (usá DD/MM/AAAA)."
    nuevo_id = db.agregar_pendiente(descripcion, monto, fecha)
    return f"Anotado (#{nuevo_id}): {descripcion} — ${monto:,.2f}, vence {fecha_str}."


def cmd_pendientes():
    pendientes = db.listar_pendientes(solo_no_pagados=True)
    if not pendientes:
        return "No tenés pendientes de pago 🎉"
    lineas = ["<b>Pendientes:</b>"]
    for p in pendientes:
        lineas.append(f"#{p['id']} {p['descripcion']} — ${p['monto']:,.2f} (vence {p['fecha_vencimiento']})")
    return "\n".join(lineas)


def cmd_pagado(texto_args):
    try:
        id_pendiente = int(texto_args.strip())
    except ValueError:
        return "Usá: /pagado ID (el número que aparece en /pendientes)"
    if db.marcar_pagado(id_pendiente):
        return f"Marcado como pagado #{id_pendiente}."
    return f"No encontré el pendiente #{id_pendiente}."


def cmd_corregir(texto_args):
    campo, _, valor = texto_args.strip().partition(" ")
    campo = campo.lower()
    valor = valor.strip()
    if not campo or not valor:
        return ("Usá: /corregir cuenta galicia | /corregir monto 1500 | /corregir categoria super")

    kwargs = {}
    if campo == "cuenta":
        cuenta = buscar_cuenta(valor)
        if not cuenta:
            return f"No reconozco esa cuenta: {valor}"
        kwargs["nueva_cuenta"] = cuenta
    elif campo == "monto":
        monto = parsear_monto(valor)
        if monto is None:
            return "No encontré un monto ahí."
        kwargs["nuevo_monto"] = monto
    elif campo == "categoria":
        kwargs["nueva_categoria"] = valor.capitalize()
    else:
        return "Los campos válidos son: cuenta, monto, categoria."

    resultado = db.corregir_ultimo_gasto(**kwargs)
    if resultado is None:
        return "No encontré ningún gasto cargado este mes para corregir."
    vieja, nueva = resultado
    return (f"Corregido el último gasto:\n"
            f"${vieja['monto']:,.2f} en {vieja['categoria']} ({vieja['cuenta']})\n"
            f"→ ${nueva['monto']:,.2f} en {nueva['categoria']} ({nueva['cuenta']})")


def cmd_deshacer():
    info = db.deshacer_ultimo_gasto()
    if info is None:
        return "No encontré ningún gasto cargado este mes para deshacer."
    return f"Borrado: ${info['monto']:,.2f} en {info['categoria']} ({info['cuenta']})."


# ---------- Rutas ----------

@app.route("/")
def health():
    return "Bot de gastos activo."


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True) or {}
    message = update.get("message") or update.get("edited_message")
    if not message:
        return jsonify(ok=True)

    chat_id = str(message["chat"]["id"])
    texto = message.get("text", "")

    if chat_id != CHAT_ID:
        return jsonify(ok=True)

    if texto.startswith("/"):
        partes = texto.split(" ", 1)
        comando = partes[0].lower()
        args = partes[1] if len(partes) > 1 else ""

        if comando in ("/start", "/help", "/ayuda"):
            respuesta = cmd_help()
        elif comando == "/resumen":
            respuesta = cmd_resumen()
        elif comando == "/saldos":
            respuesta = cmd_saldos()
        elif comando == "/invertir":
            respuesta = cmd_invertir(args)
        elif comando == "/rendimiento":
            respuesta = cmd_rendimiento(args)
        elif comando == "/pendiente":
            respuesta = cmd_pendiente(args)
        elif comando == "/pendientes":
            respuesta = cmd_pendientes()
        elif comando == "/pagado":
            respuesta = cmd_pagado(args)
        elif comando == "/corregir":
            respuesta = cmd_corregir(args)
        elif comando == "/deshacer":
            respuesta = cmd_deshacer()
        elif comando == "/planilla":
            respuesta = f"Acá está: {db.url_planilla()}"
        else:
            respuesta = "No conozco ese comando. Probá /help"
    elif es_ahorro(texto):
        monto = parsear_monto(texto)
        if monto is None:
            respuesta = "No encontré ningún monto ahí. Ej: <i>ahorre 5000</i>"
        else:
            db.agregar_ahorro_manual(monto)
            respuesta = f"Anotado como ahorro: ${monto:,.2f} 🐷"
    elif es_ingreso(texto):
        resultado = parsear_ingreso(texto)
        if resultado is None:
            respuesta = "No encontré ningún monto ahí. Ej: <i>cobre 300000 en galicia</i>"
        else:
            monto, cuenta, descripcion = resultado
            db.agregar_ingreso(monto, cuenta, descripcion)
            respuesta = f"Anotado: ingreso de ${monto:,.2f} en {cuenta}."
    else:
        resultado = parsear_gasto(texto)
        if resultado is None:
            respuesta = ("No encontré ningún monto en tu mensaje. "
                         "Escribí algo como: <i>gaste 500 en comida</i>")
        else:
            monto, categoria, descripcion, cuenta = resultado
            db.agregar_gasto(monto, categoria, descripcion, cuenta)
            respuesta = f"Anotado: ${monto:,.2f} en {categoria} ({cuenta})."

    enviar_mensaje(respuesta, chat_id)
    return jsonify(ok=True)


@app.route("/cron/diario")
def cron_diario():
    token = request.args.get("token")
    if token != CRON_SECRET:
        return "unauthorized", 401

    avisos = 0

    cerrado = db.rollover_si_corresponde()
    if cerrado:
        enviar_mensaje(
            f"<b>Se cerró el mes {cerrado['mes']}</b>\n"
            f"Total gastado: ${cerrado['total_gastado']:,.2f}\n"
            f"Ahorro total: ${cerrado['ahorro_total']:,.2f}\n\n"
            f"Abrí una hoja nueva para este mes. Revisá /saldos cuando quieras."
        )
        avisos += 1

    por_vencer = db.pendientes_por_vencer(dias=3)
    if por_vencer:
        lineas = ["<b>Recordatorio de pagos:</b>"]
        for p in por_vencer:
            if p["dias_restantes"] < 0:
                estado = f"vencido hace {abs(p['dias_restantes'])} día(s)"
            elif p["dias_restantes"] == 0:
                estado = "vence HOY"
            else:
                estado = f"vence en {p['dias_restantes']} día(s)"
            lineas.append(f"#{p['id']} {p['descripcion']} — ${p['monto']:,.2f} ({estado})")
        enviar_mensaje("\n".join(lineas))
        avisos += 1

    return jsonify(ok=True, avisos=avisos)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
