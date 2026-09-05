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
EN_CATEGORIA_RE = re.compile(r"\ben\b\s+([A-Za-zÀ-ÿÑñ]+)", re.IGNORECASE)
DE_CATEGORIA_RE = re.compile(r"\bde\b\s+([A-Za-zÀ-ÿÑñ]+)", re.IGNORECASE)
AHORRO_RE = re.compile(r"\bahorr", re.IGNORECASE)
INGRESO_RE = re.compile(r"\b(cobr|ingres|deposit|recib)", re.IGNORECASE)
TRANSFERENCIA_RE = re.compile(r"\btransfer|\btraspas", re.IGNORECASE)
DE_A_RE = re.compile(r"\bde\s+(.+?)\s+\ba\b\s+(.+)$", re.IGNORECASE)
CUENTA_CON_RE = re.compile(r"\bcon\s+(.+)$", re.IGNORECASE)
CUENTA_CON_EN_RE = re.compile(r"\b(?:con|en)\s+(.+)$", re.IGNORECASE)
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


def es_ahorro(texto: str) -> bool:
    return bool(AHORRO_RE.search(texto))


def es_ingreso(texto: str) -> bool:
    return bool(INGRESO_RE.search(texto))


def es_transferencia(texto: str) -> bool:
    return bool(TRANSFERENCIA_RE.search(texto))


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


def parsear_gasto(texto: str):
    """
    Devuelve (monto, categoria, descripcion, cuenta, fecha) o None si no encuentra un monto.
    La cuenta se indica con "... con <cuenta>" (para no chocar con "en <categoria>").
    La fecha (opcional) se indica con "ayer", "anteayer" o "3/9" / "03/09/2026"; si no se
    menciona ninguna, fecha viene None (se usa el momento actual).
    """
    fecha, texto_sin_fecha = parsear_fecha(texto)

    texto_para_monto_categoria = texto_sin_fecha
    cuenta = CUENTA_DEFAULT
    m_cuenta = CUENTA_CON_RE.search(texto_sin_fecha)
    if m_cuenta:
        encontrada = _buscar_cuenta(m_cuenta.group(1))
        if encontrada:
            cuenta = encontrada
            texto_para_monto_categoria = texto_sin_fecha[:m_cuenta.start()].strip()

    monto = parsear_monto(texto_para_monto_categoria)
    if monto is None:
        return None

    categoria = "Sin categoria"
    m_en = EN_CATEGORIA_RE.search(texto_para_monto_categoria)
    m_de = DE_CATEGORIA_RE.search(texto_para_monto_categoria)
    candidato_en = m_en.group(1) if m_en else None
    if candidato_en and _buscar_cuenta(candidato_en):
        # "en <palabra>" probablemente se referia a una cuenta conocida
        # (ej. "en wallbit"), no es una categoria real -> la descartamos
        candidato_en = None
    if candidato_en:
        categoria = candidato_en.capitalize()
    elif m_de:
        categoria = m_de.group(1).capitalize()

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
