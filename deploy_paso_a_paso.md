# Guía de Despliegue Paso a Paso desde Google Cloud Shell

Este manual explica cómo probar localmente y desplegar el microservicio detector de IP directamente desde **Google Cloud Shell**, la terminal interactiva alojada en la nube de Google Cloud Platform (GCP).

---

## Ventajas de usar Google Cloud Shell

- **Entorno preconfigurado:** Incluye `gcloud CLI`, Python 3, `git`, `curl` y Docker preinstalados.
- **Autenticación automática:** No requiere ejecutar `gcloud auth login` ni descargar llaves Service Account; utiliza la identidad de tu sesión activa en la Consola de GCP.
- **Vista Previa Web (Web Preview):** Permite probar servicios HTTP locales expuestos en puertos como el `8080` directamente en tu navegador.

---

## Parte 1: Carga del Código y Pruebas en Cloud Shell

### 1.1 Abrir Google Cloud Shell
1. Inicia sesión en la [Consola de GCP](https://console.cloud.google.com/).
2. Haz clic en el ícono de **Activar Cloud Shell** (`>_`) en la barra superior derecha de la consola.
3. Espera a que se aprovisione tu máquina virtual de Cloud Shell.

---

### 1.2 Cargar o Crear los Archivos del Proyecto
Dentro de la terminal de Cloud Shell, crea el directorio del proyecto e ingresa a él:

```bash
mkdir -p ~/csa-ip-detector
cd ~/csa-ip-detector
```

Puedes crear los archivos utilizando el **Cloud Shell Editor** (botón *Open Editor* / *Abrir Editor* en la barra de Cloud Shell) o mediante comandos de terminal:

1. **Crear `main.py`:**
   ```bash
   cat << 'EOF' > main.py
   import hashlib
   import json
   import functions_framework
   from flask import Request, Response

   def extract_client_ip(request: Request) -> str:
       x_forwarded_for = request.headers.get("X-Forwarded-For")
       if x_forwarded_for:
           ip_list = [ip.strip() for ip in x_forwarded_for.split(",")]
           if ip_list and ip_list[0]:
               client_ip = ip_list[0]
               if ":" in client_ip and not client_ip.startswith("["):
                   client_ip = client_ip.split(":")[0]
               return client_ip

       x_real_ip = request.headers.get("X-Real-IP")
       if x_real_ip:
           return x_real_ip.strip()

       return request.remote_addr or "127.0.0.1"

   @functions_framework.http
   def get_client_ip(request: Request):
       if request.method == "OPTIONS":
           headers = {
               "Access-Control-Allow-Origin": "*",
               "Access-Control-Allow-Methods": "GET, OPTIONS",
               "Access-Control-Allow-Headers": "Content-Type, Authorization",
               "Access-Control-Max-Age": "3600",
           }
           return ("", 204, headers)

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

       ip_address = extract_client_ip(request)
       hash_param = request.args.get("hash", "false").strip().lower()
       is_hashed = hash_param in ["true", "1", "yes"]

       if is_hashed:
           final_ip = hashlib.sha256(ip_address.encode("utf-8")).hexdigest()
       else:
           final_ip = ip_address

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
   EOF
   ```

2. **Crear `requirements.txt`:**
   ```bash
   cat << 'EOF' > requirements.txt
   functions-framework>=3.0.0
   flask>=2.0.0
   EOF
   ```

---

### 1.3 Pruebas de Funcionamiento Local en Cloud Shell

1. Instala las dependencias en el entorno de Cloud Shell:
   ```bash
   pip install -r requirements.txt
   ```

2. Ejecuta el servidor local emulado de Cloud Functions:
   ```bash
   functions-framework --target get_client_ip --debug --port 8080
   ```

3. **Ejecutar Pruebas (Abre una segunda pestaña en Cloud Shell haciendo clic en el ícono `+`):**

   Navega a la carpeta del proyecto en la nueva pestaña:
   ```bash
   cd ~/csa-ip-detector
   ```

   - **Prueba 1: Obtener IP en Texto Plano**
     ```bash
     curl -X GET "http://localhost:8080/?hash=false"
     ```
     *Salida esperada:* `{"client_ip": "127.0.0.1", "is_hashed": false}`

   - **Prueba 2: Simular IP de Cliente desde Balanceador de Carga**
     ```bash
     curl -X GET -H "X-Forwarded-For: 203.0.113.195, 10.0.0.1" "http://localhost:8080/?hash=false"
     ```
     *Salida esperada:* `{"client_ip": "203.0.113.195", "is_hashed": false}`

   - **Prueba 3: Obtener IP Hasheada con SHA-256 (`?hash=true`)**
     ```bash
     curl -X GET -H "X-Forwarded-For: 203.0.113.195" "http://localhost:8080/?hash=true"
     ```
     *Salida esperada:* `{"client_ip": "ea3f6e8890630ff034f9906f0c2d429df551b6505c1d9d8d28b0262f650dbb68", "is_hashed": true}`

   - **Prueba 4: Validar CORS Preflight (`OPTIONS`)**
     ```bash
     curl -i -X OPTIONS "http://localhost:8080/"
     ```
     *Salida esperada:* Respuesta HTTP `204 No Content` con encabezados `Access-Control-Allow-Origin: *`.

---

## Parte 2: Despliegue en GCP usando `gcloud CLI` en Cloud Shell

### 2.1 Configuración del Proyecto e Infraestructura

1. Configura el **Project ID** activo en Cloud Shell (reemplaza `TU_PROJECT_ID` con tu ID de proyecto real):
   ```bash
   gcloud config set project TU_PROJECT_ID
   ```

2. Habilita las APIs necesarias en tu proyecto de GCP:
   ```bash
   gcloud services enable \
     cloudfunctions.googleapis.com \
     run.googleapis.com \
     cloudbuild.googleapis.com \
     artifactregistry.googleapis.com
   ```

---

### 2.2 Roles y Permisos de IAM Necesarios

Asegúrate de que la cuenta con la que iniciaste sesión en Cloud Shell tenga asignados los siguientes roles en el proyecto de GCP (en *IAM & Admin* -> *IAM*):

- **Cloud Functions Developer** (`roles/cloudfunctions.developer`)
- **Cloud Run Admin** (`roles/run.admin`)
- **Service Account User** (`roles/iam.serviceAccountUser`)
- **Artifact Registry Administrator** (`roles/artifactregistry.admin`)

---

### 2.3 Comando de Despliegue: Cloud Functions (2da Gen)

Desde la pestaña principal de Cloud Shell en la carpeta `~/csa-ip-detector`, ejecuta:

```bash
gcloud functions deploy csa-ip-detector \
  --gen2 \
  --runtime=python311 \
  --region=us-central1 \
  --source=. \
  --entry-point=get_client_ip \
  --trigger-http \
  --allow-unauthenticated \
  --min-instances=0 \
  --max-instances=10 \
  --memory=256Mi \
  --cpu=0.16
```

#### Explicación de las Banderas Relevantes:
- `--gen2`: Utiliza la arquitectura de 2da generación basada en Cloud Run.
- `--entry-point=get_client_ip`: Apunta a la función `@functions_framework.http` en `main.py`.
- `--trigger-http`: Invocación vía HTTP/HTTPS.
- `--allow-unauthenticated`: **Crucial.** Otorga acceso público implícito (`allUsers`) para que el script JavaScript enviado desde Google Tag Manager en el navegador del usuario pueda invocar el servicio sin credenciales IAM.

---

### 2.4 Comando de Despliegue Alternativo: Cloud Run Directo

Si prefieres desplegarlo como un servicio nativo de Cloud Run:

```bash
gcloud run deploy csa-ip-detector \
  --source=. \
  --region=us-central1 \
  --allow-unauthenticated \
  --min-instances=0 \
  --max-instances=10 \
  --memory=256Mi
```

---

### 2.5 Obtener la URL del Servicio Desplegado

Al finalizar el despliegue, el comando imprimirá la URL pública. También puedes consultar la URL explícitamente ejecutando:

- **Para Cloud Functions (2da Gen):**
  ```bash
  gcloud functions describe csa-ip-detector \
    --region=us-central1 \
    --format="value(serviceConfig.uri)"
  ```

- **Para Cloud Run:**
  ```bash
  gcloud run services describe csa-ip-detector \
    --region=us-central1 \
    --format="value(status.url)"
  ```

**Ejemplo de URL devuelta:**
`https://csa-ip-detector-abc123xyz-uc.a.run.app`

---

### 2.6 Verificación Final en Producción

Realiza una prueba directamente hacia el endpoint expuesto en GCP:

```bash
curl -X GET "https://TU-URL-DESPLEGADA.a.run.app/?hash=true"
```

**Resultado esperado:**
```json
{
  "client_ip": "a3f5b2c1d8e9...[hash-64-caracteres]...",
  "is_hashed": true
}
```

¡Listo! Utiliza esta URL HTTPS para configurarla en el **Custom HTML Tag** de **Google Tag Manager** según lo detallado en [proyecto_detalle.md](proyecto_detalle.md).

