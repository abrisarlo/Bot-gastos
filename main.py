import os
import time
import requests
from datetime import datetime

from flask import Flask, request, jsonify

import sheets_manager as db
from parser import (parsear_gasto, parsear_ingreso, parsear_monto, es_ahorro, es_ingreso,
                     buscar_cuenta, buscar_todas_cuentas, es_transferencia, parsear_transferencia,
                     es_mencion_pendiente, normalizar_categoria)

app = Flask(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
CRON_SECRET = os.environ.get("CRON_SECRET", "cambiame")

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Guarda los update_id ya procesados, para no duplicar un gasto si Telegram
# reintenta mandar el mismo mensaje (pasa cuando el servidor tarda en responder).
_UPDATES_PROCESADOS = set()
_UPDATES_MAX = 500

# Cuando el bot no esta seguro de la categoria, ya guarda el gasto como
# "Sin categoria" (para no perder plata si el servidor se reinicia) y solo
# recuerda que esta esperando la respuesta, para corregir la categoria del
# ULTIMO gasto cuando llegue el proximo mensaje de ese chat.
# chat_id -> {"ts": epoch}
_PENDIENTE_CATEGORIA = {}
_PENDIENTE_TTL_SEG = 10 * 60


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
        "<i>gaste 500 en comida ayer</i> (o \"anteayer\", o una fecha tipo \"3/9\")\n"
        "<i>cobre 300000 en mercado pago</i>\n"
        "<i>transferi 5000 de efectivo a galicia</i>\n"
        "<i>ahorre 5000</i>\n\n"
        "Cuentas que reconozco: efectivo, galicia, mercado pago, wallbit, cuenta dni\n\n"
        "Comandos:\n"
        "/resumen — total gastado, ingreso, ahorro y categorías del mes\n"
        "/saldos — cuánto tenés en cada cuenta y lo invertido\n"
        "/invertir Monto — suma plata a tu saldo invertido\n"
        "/rendimiento Monto — anota lo que rindió lo invertido este mes\n"
        "/pendiente Descripcion - Monto - DD/MM/AAAA — algo que VOS tenés que pagar\n"
        "/pendientes — lista lo que falta pagar\n"
        "/pagado ID — marca un pendiente como pagado\n"
        "/cobrar Descripcion - Monto - Quien — plata que te tienen que dar a vos\n"
        "/porcobrar — lista lo que te deben\n"
        "/cobrado ID — marca algo como ya cobrado\n"
        "/planilla — te mando el link a la planilla de Google Sheets\n\n"
        "¿Te equivocaste en un gasto?\n"
        "/gastos — ver los últimos gastos con su número de fila\n"
        "/corregir cuenta galicia — corrige el último gasto\n"
        "/corregir 8 cuenta galicia — corrige la fila 8\n"
        "/corregir categoria:comida cuenta galicia — corrige el más reciente con esa categoría\n"
        "(cuenta, monto o categoria funcionan igual en los tres formatos)\n"
        "/deshacer — borra el último gasto (también acepta fila o categoria: igual que /corregir)\n"
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


def cmd_recalcularsaldos():
    anteriores, nuevos = db.recalcular_saldos_desde_historial()
    lineas = ["<b>Saldos recalculados desde todo lo anotado:</b>"]
    for cuenta, nuevo in nuevos.items():
        antes = anteriores.get(cuenta, 0.0)
        lineas.append(f"• {cuenta}: ${antes:,.2f} → ${nuevo:,.2f}")
    lineas.append("\n(Invertido no se tocó, se carga aparte con /invertir)")
    return "\n".join(lineas)


def cmd_detallesaldo(texto_args):
    cuenta = buscar_cuenta(texto_args.strip())
    if not cuenta:
        return "Usá: /detallesaldo galicia (o efectivo, mercado pago, wallbit, cuenta dni)"
    d = db.detalle_cuenta(cuenta)
    return (
        f"<b>Desglose de {d['cuenta']}:</b>\n"
        f"Ingresos: +${d['total_ingresos']:,.2f} ({d['cant_ingresos']} filas)\n"
        f"Gastos: -${d['total_gastos']:,.2f} ({d['cant_gastos']} filas)\n"
        f"Transferencias recibidas: +${d['total_transf_entrante']:,.2f}\n"
        f"Transferencias enviadas: -${d['total_transf_saliente']:,.2f} ({d['cant_transf']} transferencias en total)\n"
        f"<b>Saldo según esta cuenta: ${d['saldo_calculado']:,.2f}</b>\n"
        f"Saldo actual guardado en Cuentas: ${d['saldo_actual_en_cuentas']:,.2f}"
    )


def cmd_transferir(texto_args):
    """Formato de respaldo: /transferir monto origen destino (ej: /transferir 5000 efectivo galicia)"""
    partes = texto_args.split()
    if len(partes) < 3:
        return ("Usá: /transferir monto origen destino\n"
                "Ejemplo: /transferir 5000 efectivo galicia")
    monto = parsear_monto(partes[0])
    if monto is None:
        return "No encontré un monto ahí."
    origen = buscar_cuenta(partes[1])
    destino = buscar_cuenta(" ".join(partes[2:]))
    if not origen:
        return f"No reconozco la cuenta de origen: {partes[1]}"
    if not destino:
        return f"No reconozco la cuenta de destino: {' '.join(partes[2:])}"
    if origen == destino:
        return "El origen y el destino son la misma cuenta."
    db.transferir(monto, origen, destino)
    return f"Transferido ${monto:,.2f} de {origen} a {destino}."


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


def cmd_cobrar(texto_args):
    partes = [p.strip() for p in texto_args.split(" - ")]
    if len(partes) not in (2, 3):
        return ("Formato: /cobrar Descripcion - Monto - Quien (Quien es opcional)\n"
                "Ejemplo: /cobrar Cervezas - 5880 - Martu")
    descripcion, monto_str = partes[0], partes[1]
    quien = partes[2] if len(partes) == 3 else ""
    monto = parsear_monto(monto_str)
    if monto is None:
        return "No pude leer el monto."
    nuevo_id = db.agregar_por_cobrar(descripcion, monto, quien)
    quien_txt = f" a {quien}" if quien else ""
    return f"Anotado (#{nuevo_id}): te tienen que dar ${monto:,.2f} por {descripcion}{quien_txt}."


def cmd_porcobrar():
    items = db.listar_por_cobrar(solo_no_cobrados=True)
    if not items:
        return "No tenés nada pendiente de cobrar 🎉"
    lineas = ["<b>Por cobrar:</b>"]
    for it in items:
        quien_txt = f" ({it['quien']})" if it["quien"] else ""
        lineas.append(f"#{it['id']} {it['descripcion']}{quien_txt} — ${it['monto']:,.2f}")
    return "\n".join(lineas)


def cmd_cobrado(texto_args):
    try:
        id_cobrar = int(texto_args.strip())
    except ValueError:
        return "Usá: /cobrado ID (el número que aparece en /porcobrar)"
    if db.marcar_cobrado(id_cobrar):
        return f"Marcado como cobrado #{id_cobrar}."
    return f"No encontré el #{id_cobrar} en por cobrar."


def cmd_gastos(texto_args):
    try:
        n = int(texto_args.strip()) if texto_args.strip() else 10
    except ValueError:
        n = 10
    gastos = db.listar_gastos_mes(n)
    if not gastos:
        return "No hay ningún gasto cargado este mes."
    lineas = [f"<b>Últimos {len(gastos)} gastos</b> (fila — fecha — monto en categoría, cuenta):"]
    for g in gastos:
        lineas.append(f"#{g['fila']} — {g['fecha']} — ${g['monto']:,.2f} en {g['categoria']} ({g['cuenta']})")
    lineas.append("\nPara corregir uno: /corregir FILA cuenta galicia")
    lineas.append("Para corregir por categoría: /corregir categoria:comida cuenta galicia")
    return "\n".join(lineas)


def _sin_tilde(texto: str) -> str:
    """Normaliza tildes basicas para que 'categoria' y 'categoría' sean lo mismo."""
    return (texto.lower()
            .replace("á", "a").replace("é", "e").replace("í", "i")
            .replace("ó", "o").replace("ú", "u"))


def _resolver_selector(primer_token, resto):
    """Interpreta el primer token de /corregir o /deshacer: un numero de fila,
    'categoria:X', o nada (afecta al ultimo gasto). Devuelve (tipo, valor, resto_sin_selector)."""
    if primer_token.isdigit():
        return "id", int(primer_token), resto
    if _sin_tilde(primer_token).startswith("categoria:"):
        return "categoria", primer_token.split(":", 1)[1], resto
    return "ultimo", None, (primer_token + " " + resto).strip()


def cmd_corregir(texto_args):
    primer_token, _, resto = texto_args.strip().partition(" ")

    # "categoria:X" (con o sin espacio despues de los dos puntos, con o sin
    # tilde) es ambiguo: casi siempre el usuario quiere "cambiale la
    # categoria a X" (afecta al ultimo gasto), no "busca el gasto que ya
    # tiene esa categoria". Solo lo tratamos como selector cuando ademas
    # viene claramente pegado un campo despues (ej: "categoria:comida cuenta galicia").
    if _sin_tilde(primer_token).startswith("categoria:"):
        valor_pegado = primer_token.split(":", 1)[1].strip()
        if valor_pegado and resto.strip():
            selector_tipo, selector_valor, campo_valor = "categoria", valor_pegado, resto
        else:
            valor_directo = (valor_pegado + " " + resto).strip()
            selector_tipo, selector_valor = "ultimo", None
            campo_valor = f"categoria {valor_directo}"
    else:
        selector_tipo, selector_valor, campo_valor = _resolver_selector(primer_token, resto)

    campo, _, valor = campo_valor.strip().partition(" ")
    campo = _sin_tilde(campo).rstrip(":")
    valor = valor.strip()

    if campo in ("cuenta", "monto", "categoria") and valor:
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

        resultado, total = db.corregir_gasto(selector_tipo, selector_valor, **kwargs)
        if resultado is None:
            if selector_tipo == "categoria":
                return f"No encontré ningún gasto con categoría '{selector_valor}' este mes."
            if selector_tipo == "id":
                return f"No encontré ningún gasto en la fila {selector_valor}."
            return "No encontré ningún gasto cargado este mes para corregir."

        vieja, nueva = resultado
        aviso = ""
        if selector_tipo == "categoria" and total > 1:
            aviso = f"\n(Había {total} con esa categoría, corregí el más reciente — fila {vieja['fila']})"
        return (f"Corregido (fila {vieja['fila']}):\n"
                f"${vieja['monto']:,.2f} en {vieja['categoria']} ({vieja['cuenta']})\n"
                f"→ ${nueva['monto']:,.2f} en {nueva['categoria']} ({nueva['cuenta']}){aviso}")

    # No vino en el formato exacto: no adivinamos ni aplicamos nada solo,
    # pero intentamos sugerir el comando correcto para que lo copie y mande.
    sugerencias = []
    cuentas_mencionadas = buscar_todas_cuentas(campo_valor)
    prefijo = "" if selector_tipo == "ultimo" else f"{primer_token} "
    if len(cuentas_mencionadas) == 1:
        sugerencias.append(f"/corregir {prefijo}cuenta {cuentas_mencionadas[0]}")
    elif len(cuentas_mencionadas) > 1:
        sugerencias.append(
            f"Mencionaste más de una cuenta ({', '.join(cuentas_mencionadas)}) — "
            f"decime cuál es la correcta, ej: /corregir {prefijo}cuenta {cuentas_mencionadas[0]}"
        )
    monto_mencionado = parsear_monto(campo_valor)
    if monto_mencionado is not None and "monto" in campo_valor.lower():
        sugerencias.append(f"/corregir {prefijo}monto {monto_mencionado:g}")

    mensaje = ("Para corregir necesito el formato exacto, así solo:\n"
               "/corregir cuenta galicia (afecta al último gasto)\n"
               "/corregir FILA cuenta galicia (ej: /corregir 8 cuenta galicia)\n"
               "/corregir categoria:comida cuenta galicia\n"
               "También funciona con monto y categoria en vez de cuenta.\n"
               "Mandá /gastos para ver los números de fila.")
    if sugerencias:
        mensaje += "\n\n¿Quisiste decir esto?\n" + "\n".join(sugerencias)
    return mensaje


def cmd_deshacer(texto_args):
    texto_args = texto_args.strip()
    selector_tipo, selector_valor, _ = _resolver_selector(texto_args, "") if texto_args else ("ultimo", None, "")
    info, total = db.deshacer_gasto(selector_tipo, selector_valor)
    if info is None:
        if selector_tipo == "categoria":
            return f"No encontré ningún gasto con categoría '{selector_valor}' este mes."
        if selector_tipo == "id":
            return f"No encontré ningún gasto en la fila {selector_valor}."
        return "No encontré ningún gasto cargado este mes para deshacer."
    aviso = ""
    if selector_tipo == "categoria" and total > 1:
        aviso = f" (había {total}, borré el más reciente — fila {info['fila']})"
    return f"Borrado (fila {info['fila']}): ${info['monto']:,.2f} en {info['categoria']} ({info['cuenta']}).{aviso}"


# ---------- Rutas ----------

@app.route("/")
def health():
    return "Bot de gastos activo."


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True) or {}

    update_id = update.get("update_id")
    if update_id is not None:
        if update_id in _UPDATES_PROCESADOS:
            return jsonify(ok=True)  # ya lo procesamos, Telegram esta reintentando
        _UPDATES_PROCESADOS.add(update_id)
        if len(_UPDATES_PROCESADOS) > _UPDATES_MAX:
            _UPDATES_PROCESADOS.difference_update(
                sorted(_UPDATES_PROCESADOS)[:_UPDATES_MAX // 2]
            )

    message = update.get("message") or update.get("edited_message")
    if not message:
        return jsonify(ok=True)

    chat_id = str(message["chat"]["id"])
    texto = message.get("text", "")

    if chat_id != CHAT_ID:
        return jsonify(ok=True)

    es_respuesta_categoria = False
    if not texto.startswith("/") and chat_id in _PENDIENTE_CATEGORIA:
        if time.time() - _PENDIENTE_CATEGORIA[chat_id]["ts"] <= _PENDIENTE_TTL_SEG:
            es_respuesta_categoria = True
        else:
            _PENDIENTE_CATEGORIA.pop(chat_id, None)  # la pregunta quedo vieja, se descarta

    if texto.startswith("/"):
        _PENDIENTE_CATEGORIA.pop(chat_id, None)  # un comando cancela la pregunta pendiente
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
        elif comando == "/recalcularsaldos":
            respuesta = cmd_recalcularsaldos()
        elif comando == "/detallesaldo":
            respuesta = cmd_detallesaldo(args)
        elif comando == "/transferir":
            respuesta = cmd_transferir(args)
        elif comando == "/pendiente":
            respuesta = cmd_pendiente(args)
        elif comando == "/pendientes":
            respuesta = cmd_pendientes()
        elif comando == "/pagado":
            respuesta = cmd_pagado(args)
        elif comando == "/cobrar":
            respuesta = cmd_cobrar(args)
        elif comando == "/porcobrar":
            respuesta = cmd_porcobrar()
        elif comando == "/cobrado":
            respuesta = cmd_cobrado(args)
        elif comando == "/gastos":
            respuesta = cmd_gastos(args)
        elif comando == "/corregir":
            respuesta = cmd_corregir(args)
        elif comando == "/deshacer":
            respuesta = cmd_deshacer(args)
        elif comando == "/planilla":
            respuesta = f"Acá está: {db.url_planilla()}"
        else:
            respuesta = "No conozco ese comando. Probá /help"
    elif es_respuesta_categoria:
        _PENDIENTE_CATEGORIA.pop(chat_id, None)
        categoria = normalizar_categoria(texto.strip())
        resultado, _total = db.corregir_gasto("ultimo", None, nueva_categoria=categoria)
        if resultado is None:
            respuesta = "No encontré el gasto para corregirle la categoría."
        else:
            vieja, nueva = resultado
            respuesta = f"Listo, categoría actualizada: ${nueva['monto']:,.2f} en {categoria} ({nueva['cuenta']})."
    elif es_ahorro(texto):
        monto = parsear_monto(texto)
        if monto is None:
            respuesta = "No encontré ningún monto ahí. Ej: <i>ahorre 5000</i>"
        else:
            db.agregar_ahorro_manual(monto)
            respuesta = f"Anotado como ahorro: ${monto:,.2f} 🐷"
    elif es_transferencia(texto):
        resultado = parsear_transferencia(texto)
        if resultado is None:
            respuesta = ("No pude entender la transferencia. Ej: <i>transferi 5000 de efectivo a galicia</i>\n"
                         "O usá: /transferir 5000 efectivo galicia")
        else:
            monto, origen, destino = resultado
            db.transferir(monto, origen, destino)
            respuesta = f"Transferido ${monto:,.2f} de {origen} a {destino}."
    elif es_mencion_pendiente(texto):
        monto_sugerido = parsear_monto(texto)
        monto_txt = f"{monto_sugerido:g}" if monto_sugerido is not None else "Monto"
        respuesta = (
            "Para que quede bien anotado (no lo cargué como gasto), decime cuál es:\n"
            f"• Algo que VOS tenés que pagar: /pendiente Descripcion - {monto_txt} - DD/MM/AAAA\n"
            f"• Plata que te tienen que dar a vos: /cobrar Descripcion - {monto_txt} - Quien"
        )
    elif es_ingreso(texto):
        resultado = parsear_ingreso(texto)
        if resultado is None:
            respuesta = "No encontré ningún monto ahí. Ej: <i>cobre 300000 en galicia</i>"
        else:
            monto, cuenta, descripcion, fecha = resultado
            db.agregar_ingreso(monto, cuenta, descripcion, fecha=fecha)
            aviso_fecha = f" (fecha {fecha.strftime('%d/%m/%Y')})" if fecha else ""
            respuesta = f"Anotado: ingreso de ${monto:,.2f} en {cuenta}{aviso_fecha}."
    else:
        resultado = parsear_gasto(texto)
        if resultado is None:
            respuesta = ("No encontré ningún monto en tu mensaje. "
                         "Escribí algo como: <i>gaste 500 en comida</i>")
        else:
            monto, categoria, descripcion, cuenta, fecha = resultado
            db.agregar_gasto(monto, categoria, descripcion, cuenta, fecha=fecha)
            aviso_fecha = f" (fecha {fecha.strftime('%d/%m/%Y')})" if fecha else ""
            if categoria == "Sin categoria":
                _PENDIENTE_CATEGORIA[chat_id] = {"ts": time.time()}
                respuesta = (f"Anotado: ${monto:,.2f} en Sin categoria ({cuenta}){aviso_fecha}.\n"
                             f"¿En qué categoría lo dejo? Respondé solo con la categoría (ej: <i>comida</i>).")
            else:
                respuesta = f"Anotado: ${monto:,.2f} en {categoria} ({cuenta}){aviso_fecha}."
                respuesta = f"Anotado: ${monto:,.2f} en {categoria} ({cuenta}){aviso_fecha}."

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
