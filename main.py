import hashlib
import ipaddress
import json
import functions_framework
from flask import Request, Response

def clean_ip(ip_str: str) -> str:
    """
    Limpia y valida una dirección IP (IPv4 o IPv6), removiendo puertos si están presentes.
    """
    ip_str = ip_str.strip()
    # Si viene con corchetes (ej. "[2001:db8::1]:8080" o "[2001:db8::1]")
    if ip_str.startswith("["):
        end_bracket = ip_str.find("]")
        if end_bracket != -1:
            ip_str = ip_str[1:end_bracket]
    # Si es IPv4 con puerto (ej. "203.0.113.195:54321")
    elif ip_str.count(":") == 1 and "." in ip_str:
        ip_str = ip_str.split(":")[0]

    try:
        return str(ipaddress.ip_address(ip_str))
    except ValueError:
        return ip_str

def extract_client_ip(request: Request) -> str:
    """
    Extrae la dirección IP real del cliente considerando encabezados de proxies y balanceadores de carga de GCP.
    Soporta direcciones IPv4 e IPv6.
    """
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        # X-Forwarded-For puede contener múltiples IPs separadas por comas: "client, proxy1, proxy2"
        ip_list = [ip.strip() for ip in x_forwarded_for.split(",")]
        if ip_list and ip_list[0]:
            return clean_ip(ip_list[0])

    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return clean_ip(x_real_ip)

    return clean_ip(request.remote_addr or "127.0.0.1")


@functions_framework.http
def get_client_ip(request: Request):
    """
    HTTP Cloud Function de 2da generación para devolver la IP pública del cliente (en texto plano o SHA-256).
    """
    # Manejo de solicitudes preflight de CORS (HTTP OPTIONS)
    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "3600",
        }
        return ("", 204, headers)

    # Solo se permiten peticiones GET (y OPTIONS)
    if request.method != "GET":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Content-Type": "application/json",
        }
        return Response(
            json.dumps({"error": "Método no permitido. Utilice GET."}),
            status=405,
            headers=headers,
        )

    # Extracción de la IP real
    ip_address = extract_client_ip(request)

    # Evaluación del parámetro query ?hash=true
    hash_param = request.args.get("hash", "false").strip().lower()
    is_hashed = hash_param in ["true", "1", "yes"]

    # Procesamiento del valor final
    if is_hashed:
        final_ip = hashlib.sha256(ip_address.encode("utf-8")).hexdigest()
    else:
        final_ip = ip_address

    # Construcción de la respuesta JSON
    response_payload = {
        "client_ip": final_ip,
        "is_hashed": is_hashed,
    }

    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Content-Type": "application/json",
        "Cache-Control": "no-cache, no-store, must-revalidate",
    }

    return Response(
        json.dumps(response_payload, ensure_ascii=False),
        status=200,
        headers=headers,
    )
