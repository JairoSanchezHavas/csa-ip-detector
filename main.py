import hashlib
import json
import functions_framework
from flask import Request, Response

def extract_client_ip(request: Request) -> str:
    """
    Extrae la dirección IP real del cliente considerando encabezados de proxies y balanceadores de carga de GCP.
    GCP Cloud Load Balancer apéndice la IP del cliente al principio del encabezado X-Forwarded-For.
    """
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        # X-Forwarded-For puede contener múltiples IPs separadas por comas: "client, proxy1, proxy2"
        ip_list = [ip.strip() for ip in x_forwarded_for.split(",")]
        if ip_list and ip_list[0]:
            client_ip = ip_list[0]
            # Eliminar puerto si viniera adjunto (ej. "203.0.113.195:12345" o "[2001:db8::1]:12345")
            if ":" in client_ip and not client_ip.startswith("["):
                client_ip = client_ip.split(":")[0]
            return client_ip

    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip.strip()

    return request.remote_addr or "127.0.0.1"


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
