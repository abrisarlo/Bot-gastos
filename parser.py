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

NUMERO_RE = re.compile(r"\d[\d.,]*\d|\d")
EN_CATEGORIA_RE = re.compile(r"\ben\b\s+(.+)$", re.IGNORECASE)
DE_CATEGORIA_RE = re.compile(r"\bde\b\s+(.+)$", re.IGNORECASE)
AHORRO_RE = re.compile(r"\bahorr", re.IGNORECASE)
INGRESO_RE = re.compile(r"\b(cobr|ingres|deposit|recib)", re.IGNORECASE)
CUENTA_CON_RE = re.compile(r"\bcon\s+(.+)$", re.IGNORECASE)
CUENTA_CON_EN_RE = re.compile(r"\b(?:con|en)\s+(.+)$", re.IGNORECASE)

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


def buscar_cuenta(frase: str):
    """Version publica de _buscar_cuenta, para usar desde comandos como /corregir."""
    return _buscar_cuenta(frase)


def parsear_gasto(texto: str):
    """
    Devuelve (monto, categoria, descripcion, cuenta) o None si no encuentra un monto.
    La cuenta se indica con "... con <cuenta>" (para no chocar con "en <categoria>").
    """
    texto_para_monto_categoria = texto
    cuenta = CUENTA_DEFAULT
    m_cuenta = CUENTA_CON_RE.search(texto)
    if m_cuenta:
        encontrada = _buscar_cuenta(m_cuenta.group(1))
        if encontrada:
            cuenta = encontrada
            texto_para_monto_categoria = texto[:m_cuenta.start()].strip()

    monto = parsear_monto(texto_para_monto_categoria)
    if monto is None:
        return None

    categoria = "Sin categoria"
    m_en = EN_CATEGORIA_RE.search(texto_para_monto_categoria)
    m_de = DE_CATEGORIA_RE.search(texto_para_monto_categoria)
    if m_en:
        categoria = m_en.group(1).strip().capitalize()
    elif m_de:
        categoria = m_de.group(1).strip().capitalize()

    return monto, categoria, texto.strip(), cuenta


def parsear_ingreso(texto: str):
    """
    Devuelve (monto, cuenta, descripcion) o None si no encuentra un monto.
    La cuenta se indica con "... en <cuenta>" o "... con <cuenta>".
    """
    texto_para_monto = texto
    cuenta = CUENTA_DEFAULT
    m_cuenta = CUENTA_CON_EN_RE.search(texto)
    if m_cuenta:
        encontrada = _buscar_cuenta(m_cuenta.group(1))
        if encontrada:
            cuenta = encontrada
            texto_para_monto = texto[:m_cuenta.start()].strip()

    monto = parsear_monto(texto_para_monto)
    if monto is None:
        return None
    return monto, cuenta, texto.strip()
