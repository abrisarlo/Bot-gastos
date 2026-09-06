"""
Interpreta mensajes de texto libre como gastos, ingresos o ahorros,
y detecta si mencionan una cuenta (efectivo, banco, billetera virtual).

Ejemplos que entiende:
  "gaste 500 en comida"                     -> gasto, cuenta Efectivo (default)
  "gaste 500 en comida con galicia"         -> gasto, cuenta Galicia
  "cobre 300000 en mercado pago"            -> ingreso, cuenta Mercado Pago
  "ahorre 5000"                             -> ahorro manual
"""
import re
from datetime import date, timedelta

NUMERO_RE = re.compile(r"\d[\d.,]*\d|\d")
ARTICULO = r"(?:el|la|los|las|un|una|unos|unas)\s+"
EN_CATEGORIA_RE = re.compile(rf"\ben\b\s+(?:{ARTICULO})?([A-Za-zÀ-ÿÑñ]+)", re.IGNORECASE)
DE_CATEGORIA_RE = re.compile(rf"\bde\b\s+(?:{ARTICULO})?([A-Za-zÀ-ÿÑñ]+)", re.IGNORECASE)
AHORRO_RE = re.compile(r"\bahorr", re.IGNORECASE)
INGRESO_RE = re.compile(r"\b(cobr|ingres|deposit|recib)", re.IGNORECASE)
TRANSFERENCIA_RE = re.compile(r"\btransfer|\btraspas", re.IGNORECASE)
PENDIENTE_RE = re.compile(r"\bpendient", re.IGNORECASE)
DE_A_RE = re.compile(r"\bde\s+(.+?)\s+\ba\b\s+(.+)$", re.IGNORECASE)
CUENTA_CON_RE = re.compile(r"\bcon\s+(.+)$", re.IGNORECASE)
CUENTA_CON_EN_RE = re.compile(r"\b(?:con|en)\s+(.+)$", re.IGNORECASE)
CUENTA_PALABRA_RE = re.compile(r"\b(?:en|con)\s+cuenta\s+(.+)$", re.IGNORECASE)
ANTEAYER_RE = re.compile(r"\banteayer\b|\bantes\s+de\s+ayer\b", re.IGNORECASE)
AYER_RE = re.compile(r"\bayer\b", re.IGNORECASE)
FECHA_EXPLICITA_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b")

# claves de busqueda (mas largas primero) -> nombre canonico de la cuenta
SINONIMOS_CUENTA = {
    "mercado pago": "Mercado Pago",
    "mercadopago": "Mercado Pago",
    "cuenta dni": "Cuenta DNI",
    "wallbit": "Wallbit",
    "wallabit": "Wallbit",
    "galicia": "Galicia",
    "efectivo": "Efectivo",
    "cash": "Efectivo",
    "dni": "Cuenta DNI",
    "mp": "Mercado Pago",
}
CUENTA_DEFAULT = "Efectivo"

# Palabras que se agrupan bajo una categoria mas general.
# Si una palabra no esta acá, se usa tal cual (capitalizada).
CATEGORIA_SINONIMOS = {
    # Transporte
    "uber": "Transporte", "cabify": "Transporte", "subte": "Transporte",
    "colectivo": "Transporte", "bondi": "Transporte", "taxi": "Transporte",
    "nafta": "Transporte", "combustible": "Transporte", "peaje": "Transporte",
    "sube": "Transporte", "tren": "Transporte",
    # Supermercado / comida
    "super": "Supermercado", "supermercado": "Supermercado", "coto": "Supermercado",
    "carrefour": "Supermercado", "dia": "Supermercado", "jumbo": "Supermercado",
    "almacen": "Supermercado", "verduleria": "Supermercado", "kiosco": "Supermercado",
    "comida": "Comida", "delivery": "Comida", "restaurant": "Comida",
    "restaurante": "Comida", "pedidosya": "Comida", "rappi": "Comida",
    # Servicios / hogar
    "luz": "Servicios", "gas": "Servicios", "agua": "Servicios", "internet": "Servicios",
    "telefono": "Servicios", "celular": "Servicios", "expensas": "Servicios",
    "alquiler": "Hogar", "limpieza": "Hogar",
    # Entretenimiento
    "netflix": "Streaming", "spotify": "Streaming", "disney": "Streaming",
    "hbo": "Streaming", "cine": "Entretenimiento", "salidas": "Entretenimiento",
    "birras": "Entretenimiento", "cerveza": "Entretenimiento", "bar": "Entretenimiento",
    # Salud
    "farmacia": "Salud", "medico": "Salud", "dentista": "Salud", "obra": "Salud",
}


def _normalizar_categoria(palabra: str) -> str:
    clave = palabra.strip().lower()
    return CATEGORIA_SINONIMOS.get(clave, palabra.capitalize())


def es_ahorro(texto: str) -> bool:
    return bool(AHORRO_RE.search(texto))


def es_ingreso(texto: str) -> bool:
    return bool(INGRESO_RE.search(texto))


def es_transferencia(texto: str) -> bool:
    return bool(TRANSFERENCIA_RE.search(texto))


def es_mencion_pendiente(texto: str) -> bool:
    """Detecta si el mensaje menciona 'pendiente' en lenguaje libre (no como
    comando), para no confundirlo con un gasto normal."""
    return bool(PENDIENTE_RE.search(texto))


def _normalizar_numero(bruto: str) -> str:
    """
    Interpreta numeros como se escriben en Argentina:
    "1.200.000" -> 1200000 (puntos de miles)
    "1.200.000,50" -> 1200000.50 (coma decimal)
    "1200,50" -> 1200.50
    "12.50" -> 12.50 (un solo punto con 2 decimales = decimal, no de miles)
    """
    tiene_coma = "," in bruto
    tiene_punto = "." in bruto

    if tiene_coma and tiene_punto:
        if bruto.rfind(",") > bruto.rfind("."):
            # la coma es el separador decimal, los puntos son de miles
            bruto = bruto.replace(".", "").replace(",", ".")
        else:
            # el punto es el separador decimal, las comas son de miles
            bruto = bruto.replace(",", "")
    elif tiene_coma:
        bruto = bruto.replace(",", ".")
    elif tiene_punto:
        partes = bruto.split(".")
        if len(partes) > 1 and len(partes[-1]) == 3:
            # grupos de 3 digitos -> son separadores de miles
            bruto = "".join(partes)
        # si el ultimo grupo tiene 1 o 2 digitos, el punto ya es decimal: se deja igual

    return bruto


def parsear_monto(texto: str):
    """Devuelve solo el monto (float) encontrado en el texto, o None."""
    match = NUMERO_RE.search(texto)
    if not match:
        return None
    try:
        return float(_normalizar_numero(match.group(0)))
    except ValueError:
        return None


def _buscar_cuenta(frase: str):
    frase_low = frase.lower()
    for clave in sorted(SINONIMOS_CUENTA, key=len, reverse=True):
        if clave in frase_low:
            return SINONIMOS_CUENTA[clave]
    return None


def buscar_todas_cuentas(texto: str):
    """Devuelve TODAS las cuentas mencionadas en el texto, en el orden en que aparecen
    (util para sugerir un /corregir cuando el usuario escribio en lenguaje libre)."""
    texto_low = texto.lower()
    posiciones = []
    for clave, nombre in SINONIMOS_CUENTA.items():
        idx = texto_low.find(clave)
        if idx != -1:
            posiciones.append((idx, nombre))
    posiciones.sort(key=lambda x: x[0])
    vistos = set()
    resultado = []
    for _, nombre in posiciones:
        if nombre not in vistos:
            vistos.add(nombre)
            resultado.append(nombre)
    return resultado


def buscar_cuenta(frase: str):
    """Version publica de _buscar_cuenta, para usar desde comandos como /corregir."""
    return _buscar_cuenta(frase)


def parsear_fecha(texto: str):
    """
    Busca una fecha mencionada en el texto: "ayer", "anteayer", o una fecha
    explicita tipo "3/9" o "03/09/2026". Devuelve (fecha_o_None, texto_sin_esa_parte).
    Si no encuentra nada, fecha es None (se interpreta como "ahora").
    """
    m = ANTEAYER_RE.search(texto)
    if m:
        return date.today() - timedelta(days=2), (texto[:m.start()] + texto[m.end():]).strip()

    m = AYER_RE.search(texto)
    if m:
        return date.today() - timedelta(days=1), (texto[:m.start()] + texto[m.end():]).strip()

    m = FECHA_EXPLICITA_RE.search(texto)
    if m:
        dia, mes = int(m.group(1)), int(m.group(2))
        anio_str = m.group(3)
        anio = date.today().year
        if anio_str:
            anio = int(anio_str)
            if anio < 100:
                anio += 2000
        try:
            fecha = date(anio, mes, dia)
        except ValueError:
            return None, texto
        return fecha, (texto[:m.start()] + texto[m.end():]).strip()

    return None, texto


def normalizar_categoria(palabra: str) -> str:
    """Version publica de _normalizar_categoria, para usarla al confirmar
    una categoria que el usuario responde despues de una pregunta del bot."""
    return _normalizar_categoria(palabra)


def parsear_gasto(texto: str):
    """
    Devuelve (monto, categoria, descripcion, cuenta, fecha) o None si no encuentra un monto.
    La cuenta se puede indicar de tres formas (en este orden de prioridad):
      1. "... con <cuenta>"          (ej: "gaste 500 en comida con galicia")
      2. "... en/con cuenta <cuenta>" (ej: "pague 15600 en cuenta galicia")
      3. "... en <cuenta_conocida>"   (ej: "gaste 500 de uber en galicia" -> Galicia)
    La fecha (opcional) se indica con "ayer", "anteayer" o "3/9" / "03/09/2026"; si no se
    menciona ninguna, fecha viene None (se usa el momento actual).
    """
    fecha, texto_sin_fecha = parsear_fecha(texto)
    texto_trabajo = texto_sin_fecha
    cuenta = None

    # 1) "con <cuenta>" explicito
    m_con = CUENTA_CON_RE.search(texto_trabajo)
    if m_con:
        encontrada = _buscar_cuenta(m_con.group(1))
        if encontrada:
            cuenta = encontrada
            texto_trabajo = texto_trabajo[:m_con.start()].strip()

    # 2) "en/con cuenta <cuenta>" explicito (la palabra "cuenta" no es categoria)
    if cuenta is None:
        m_palabra = CUENTA_PALABRA_RE.search(texto_trabajo)
        if m_palabra:
            encontrada = _buscar_cuenta(m_palabra.group(1))
            if encontrada:
                cuenta = encontrada
                texto_trabajo = texto_trabajo[:m_palabra.start()].strip()

    monto = parsear_monto(texto_trabajo)
    if monto is None:
        return None

    categoria = "Sin categoria"
    m_en = EN_CATEGORIA_RE.search(texto_trabajo)
    m_de = DE_CATEGORIA_RE.search(texto_trabajo)
    candidato_en = m_en.group(1) if m_en else None
    if candidato_en:
        cuenta_desde_en = _buscar_cuenta(candidato_en)
        if cuenta_desde_en:
            # 3) "en <palabra>" resulto ser una cuenta conocida (ej. "en galicia"),
            # no una categoria real: la usamos como cuenta si todavia no tenemos una
            if cuenta is None:
                cuenta = cuenta_desde_en
            candidato_en = None
    if candidato_en:
        categoria = _normalizar_categoria(candidato_en)
    elif m_de:
        categoria = _normalizar_categoria(m_de.group(1))

    if cuenta is None:
        cuenta = CUENTA_DEFAULT

    return monto, categoria, texto.strip(), cuenta, fecha


def parsear_transferencia(texto: str):
    """
    Devuelve (monto, cuenta_origen, cuenta_destino) o None si no encuentra
    un monto o no puede identificar las dos cuentas.
    Ejemplo: "transferi 5000 de efectivo a galicia"
    """
    monto = parsear_monto(texto)
    if monto is None:
        return None
    m = DE_A_RE.search(texto)
    if not m:
        return None
    origen = _buscar_cuenta(m.group(1))
    destino = _buscar_cuenta(m.group(2))
    if not origen or not destino or origen == destino:
        return None
    return monto, origen, destino


def parsear_ingreso(texto: str):
    """
    Devuelve (monto, cuenta, descripcion, fecha) o None si no encuentra un monto.
    La cuenta se indica con "... en <cuenta>" o "... con <cuenta>".
    La fecha (opcional) se indica con "ayer", "anteayer" o "3/9" / "03/09/2026".
    """
    fecha, texto_sin_fecha = parsear_fecha(texto)

    texto_para_monto = texto_sin_fecha
    cuenta = CUENTA_DEFAULT
    m_cuenta = CUENTA_CON_EN_RE.search(texto_sin_fecha)
    if m_cuenta:
        encontrada = _buscar_cuenta(m_cuenta.group(1))
        if encontrada:
            cuenta = encontrada
            texto_para_monto = texto_sin_fecha[:m_cuenta.start()].strip()

    monto = parsear_monto(texto_para_monto)
    if monto is None:
        return None
    return monto, cuenta, texto.strip(), fecha
