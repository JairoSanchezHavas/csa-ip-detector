# Detalle Técnico y Arquitectura del Microservicio: Detector de IP Pública (GCP & GTM)

Este documento describe la arquitectura, la lógica de implementación interna y la guía de integración con **Google Tag Manager (GTM)** para el microservicio de detección e higienización de direcciones IP públicas en Google Cloud Platform (GCP).

---

## 1. Arquitectura y Flujo de la Solicitud

El microservicio está diseñado bajo una arquitectura *serverless* autosescalable utilizando **Google Cloud Functions de 2da generación** (sobre la infraestructura de **Google Cloud Run**).

### Diagrama del Flujo de Datos

```
[ Navegador del Usuario ]
           │
           │ 1. Ejecución de script JS desde Google Tag Manager (Custom HTML)
           ▼
[ GCP Cloud Load Balancer / Cloud Ingress ]
           │
           │ 2. Inyección de encabezados de proxy (X-Forwarded-For: <Client_IP>, <Proxy_IP>)
           ▼
[ Cloud Functions 2da Gen / Cloud Run (Python Runtime) ]
           │
           │ 3. Invocación de la función `get_client_ip(request)`
           │    a) Validación de solicitud CORS (Preflight OPTIONS / GET)
           │    b) Extracción de la IP real del cliente (primer elemento de X-Forwarded-For)
           │    c) Evaluación del query parameter `?hash=true`
           │    d) Ofuscación criptográfica SHA-256 (si aplica)
           ▼
[ Respuesta HTTP JSON ] ──> `{"client_ip": "...", "is_hashed": true|false}`
           │
           │ 4. Recepción asíncrona en el navegador
           ▼
[ window.dataLayer ] ──> `dataLayer.push({'event': 'ip_detected', 'client_ip': '...', ...})`
```

---

## 2. Lógica de Implementación Técnica

### A. Resolución de la IP Real del Cliente
Cuando un servicio en Google Cloud Platform está expuesto públicamente, las peticiones transitan a través del **Google Cloud Load Balancer (GCLB)** y capas de infraestructura interna de red.

- **El Problema:** La propiedad `request.remote_addr` de Flask/WSGI devolvería la IP del proxy o balanceador interno de GCP (rango privado o de infraestructura), no la del navegador cliente.
- **La Solución:** Leemos el encabezado HTTP `X-Forwarded-For`.
  - El estándar `X-Forwarded-For` sigue el formato: `X-Forwarded-For: client, proxy1, proxy2`.
  - La **IP del cliente original** siempre es la **primera dirección IP** en la lista separada por comas.
  - La función realiza un `.split(',')[0].strip()` para aislar la IP cliente.
  - Se remueve el número de puerto en caso de que venga adjunto (ejemplo: `203.0.113.195:54321` -> `203.0.113.195`).
  - Como mecanismos de respaldo (*fallbacks*), la función revisa el encabezado `X-Real-IP` y, finalmente, `request.remote_addr`.

```python
def clean_ip(ip_str: str) -> str:
    ip_str = ip_str.strip()
    if ip_str.startswith("["):
        end_bracket = ip_str.find("]")
        if end_bracket != -1:
            ip_str = ip_str[1:end_bracket]
    elif ip_str.count(":") == 1 and "." in ip_str:
        ip_str = ip_str.split(":")[0]

    try:
        return str(ipaddress.ip_address(ip_str))
    except ValueError:
        return ip_str

def extract_client_ip(request: Request) -> str:
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        ip_list = [ip.strip() for ip in x_forwarded_for.split(",")]
        if ip_list and ip_list[0]:
            return clean_ip(ip_list[0])
    
    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return clean_ip(x_real_ip)
        
    return clean_ip(request.remote_addr or "127.0.0.1")
```

---

### B. Manejo de CORS (Cross-Origin Resource Sharing)
Puesto que la petición se origina directamente desde el navegador web del usuario final en dominios de marketing de terceros (ej. `www.mitienda.com`), el navegador ejecuta validaciones de seguridad CORS.

1. **Solicitudes Preflight (`OPTIONS`):**
   - Cuando el navegador detecta una petición entre dominios, primero envía una solicitud HTTP con método `OPTIONS`.
   - El microservicio responde inmediatamente con código de estado HTTP `204 No Content` y los encabezados correspondientes:
     - `Access-Control-Allow-Origin: *`
     - `Access-Control-Allow-Methods: GET, OPTIONS`
     - `Access-Control-Allow-Headers: Content-Type, Authorization`
     - `Access-Control-Max-Age: 3600` (almacena en caché la autorización preflight por 1 hora para optimizar latencia).
2. **Solicitud Principal (`GET`):**
   - Incluye el encabezado `Access-Control-Allow-Origin: *` en la respuesta JSON para que el navegador permita la lectura del cuerpo de la respuesta desde cualquier origen.

---

### C. Función Criptográfica de Hashing (SHA-256) y Privacidad (PII)
Las direcciones IP son consideradas Información de Identificación Personal (**PII**) bajo normativas globales de privacidad de datos como el **GDPR (Unión Europea)** y **CCPA (California)**. Plataformas de analítica y pauta publicitaria (como Meta Conversions API, Google Analytics 4 Enhanced Conversions, TikTok Events API) exigen el envío de PII en formato **SHA-256 hexadecimal en minúsculas**.

- **Parámetro:** `?hash=true` (admite valores case-insensitive como `true`, `1`, `yes`).
- **Procesamiento:**
  ```python
  import hashlib
  final_ip = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()
  ```
- **Salida:** Una cadena de 64 caracteres hexadecimales de longitud fija.

---

### D. Formatos de Respuesta JSON

#### 1. Sin Hashing (Texto Plano) - `GET /` o `GET /?hash=false`
```json
{
  "client_ip": "203.0.113.195",
  "is_hashed": false
}
```

#### 2. Con Hashing SHA-256 - `GET /?hash=true`
```json
{
  "client_ip": "b4b9b02e6f09a52bc30a9e7f8e8f8101a9b2b3c4d5e6f7a8b9c0d1e2f3a4b5c6",
  "is_hashed": true
}
```

---

## 3. Integración en Google Tag Manager (GTM)

A continuación se presentan los scripts optimizados para implementarse en **Google Tag Manager** dentro del contenedor web de tu sitio.

### Opción A: Custom HTML Tag (Recomendada con `fetch`)

Crea un **Custom HTML Tag** en GTM con el siguiente código JavaScript. Reemplaza `https://TU-REGION-TU-PROYECTO.cloudfunctions.net/get_client_ip` por la URL pública de tu servicio desplegado.

```html
<script>
(function() {
  // Configuración del Endpoint
  var ENDPOINT_URL = "https://TU-REGION-TU-PROYECTO.cloudfunctions.net/get_client_ip?hash=true";

  // Verificación de compatibilidad con fetch
  if (typeof window.fetch === "function") {
    window.fetch(ENDPOINT_URL, {
      method: "GET",
      mode: "cors",
      cache: "no-cache"
    })
    .then(function(response) {
      if (!response.ok) {
        throw new Error("HTTP status " + response.status);
      }
      return response.json();
    })
    .then(function(data) {
      // Empujar resultado al dataLayer
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({
        'event': 'ip_detected',
        'user_client_ip': data.client_ip,
        'user_ip_is_hashed': data.is_hashed
      });
    })
    .catch(function(error) {
      console.warn("[GTM IP Detector] Error consultando servicio de IP:", error);
    });
  } else {
    // Fallback con XMLHttpRequest para navegadores antiguos
    var xhr = new XMLHttpRequest();
    xhr.open("GET", ENDPOINT_URL, true);
    xhr.onreadystatechange = function() {
      if (xhr.readyState === 4 && xhr.status === 200) {
        try {
          var data = JSON.parse(xhr.responseText);
          window.dataLayer = window.dataLayer || [];
          window.dataLayer.push({
            'event': 'ip_detected',
            'user_client_ip': data.client_ip,
            'user_ip_is_hashed': data.is_hashed
          });
        } catch (e) {
          console.warn("[GTM IP Detector] Error al parsear respuesta JSON:", e);
        }
      }
    };
    xhr.send();
  }
})();
</script>
```

---

### Configuración en la Interfaz de Google Tag Manager

1. **Crear las Variables del DataLayer:**
   - **Variable 1:**
     - Nombre en GTM: `DLV - User Client IP`
     - Tipo: Data Layer Variable
     - Data Layer Variable Name: `user_client_ip`
   - **Variable 2:**
     - Nombre en GTM: `DLV - User IP Is Hashed`
     - Tipo: Data Layer Variable
     - Data Layer Variable Name: `user_ip_is_hashed`

2. **Crear el Activador (Trigger):**
   - Nombre: `Custom Event - ip_detected`
   - Tipo de activador: Custom Event
   - Event name: `ip_detected`

3. **Asociación a Tags de Marketing:**
   - En tus Tags de Facebook Pixel / Meta Conversions API, Google Ads Enhanced Conversions o GA4, utiliza la variable `{{DLV - User Client IP}}` activando tus etiquetas con el activador `Custom Event - ip_detected`.
