# Plataforma de Validación Espectral y Multitemporal

Aplicación web (Streamlit) para **validar y calibrar de forma cruzada imágenes de dron (UAS) contra imágenes satelitales**, y para explorar datos hiperespectrales.

Los drones comerciales con sensores multiespectrales (MicaSense, Sentera, etc.) pueden entregar valores radiométricos con incertidumbre. Esta plataforma toma un sensor satelital (por ejemplo Sentinel-2) como referencia y cuantifica qué tan bien coinciden ambos sensores sobre las mismas coberturas, en una o varias fechas.

## Qué permite hacer

* **Dos modalidades de análisis**
  * **Multiespectral (dron vs satélite):** firmas espectrales, índices espectrales y regresión lineal entre sensores ($R^2$).
  * **Hiperespectral:** firma espectral continua por cobertura y explorador de bandas sobre el mapa.
* **Visor espacial** con mapa interactivo, superficie por cobertura (ha) y mapas en color real, falso color, índices y banda individual.
* **Análisis multitemporal:** hasta 10 escenas (fechas o campañas) y una pestaña de comparación global.
* **Métricas de concordancia:** además del $R^2$, pendiente, intercepto, sesgo, MAE y RMSE entre satélite y dron, por escena, cobertura y banda.
* **Exportación:** cada gráfico en PNG de alta resolución (300 dpi) y cada tabla en CSV, o **todo junto en un único ZIP** con un solo clic.
* **Modo visor:** si no se carga un archivo vectorial, la plataforma funciona solo como visor espacial.

## Requisitos

* Python **3.10 o superior**
* Conexión a internet para los mapas base (Google Satélite, OpenStreetMap y CartoDB)

Las dependencias están en `requirements.txt`. Las versiones mínimas fueron probadas, y también las versiones más recientes disponibles a octubre de 2026.

## Instalación

    # 1. (Recomendado) crear un entorno virtual
    python -m venv venv
    source venv/bin/activate          # Windows: venv\Scripts\activate
    
    # 2. Instalar dependencias
    pip install -r requirements.txt

## Ejecución

    streamlit run app.py

La aplicación se abre en `http://localhost:8501`.

## Estructura del proyecto

    .
    ├── app.py                  # Aplicación completa
    ├── requirements.txt        # Dependencias
    ├── README.md
    └── .streamlit/
        └── config.toml         # Configuración de Streamlit (límite de carga)

> **Importante:** `config.toml` debe estar dentro de la carpeta `.streamlit/` para que Streamlit lo lea. Define `server.maxUploadSize = 1000`, que permite cargar archivos de hasta 1000 MB.

## Guía de uso

Todo se configura en el panel lateral, de arriba hacia abajo:

1. **Modalidad de análisis:** *Multiespectral (dron/satélite)* o *Hiperespectral*.
2. **Archivo vectorial (opcional):** un `.zip` con el shapefile completo (`.shp`, `.shx`, `.dbf`, `.prj`) o un `.gpkg`. Luego se elige la columna que identifica la cobertura de cada polígono (ej. agua, vegetación, suelo).
3. **Escenas:** cantidad de escenas (1 a 10) y, para cada una, el GeoTIFF del dron y/o del satélite. En hiperespectral solo se carga la imagen hiperespectral.
4. **Ajustes radiométricos:** preset del satélite (o *Personalizado*) y escala/offset del dron.
5. **Configuración de bandas** (solo multiespectral): número de banda de cada color, para dron y satélite.
6. **Ejecutar plataforma.** Los resultados de cada escena se procesan al abrir su pestaña. **Reiniciar entorno** limpia la sesión.

### Datos de entrada

| Dato | Formato | Notas |
| --- | --- | --- |
| Imágenes de dron y satélite | GeoTIFF (`.tif`) | Deben estar en un sistema **proyectado en metros** (ej. UTM). Se reproyectan automáticamente al sistema del primer archivo. |
| Cobertura (opcional) | `.zip` (shapefile) o `.gpkg` | Un atributo debe identificar la cobertura de cada polígono. |
| Imagen hiperespectral | GeoTIFF multibanda | Si cada banda tiene una descripción con la longitud de onda (ej. `B450`), se usa como eje X. |

**Nombre de los archivos:** se recomienda `AAAA-MM-DD_Lugar_...tif`, por ejemplo `2025-07-15_Laguna-Verde_dron.tif`. De ahí se obtiene el título de la escena (*Laguna Verde (2025-07-15)*). Si el nombre no sigue este formato, se usa el nombre del archivo sin extensión.

> El primer archivo de la escena 1 define el sistema de coordenadas de todo el proyecto. Si está en grados (geográfico), la plataforma se detiene con un error.

### Ajuste radiométrico

La reflectancia se calcula como:

    reflectancia = (valor_del_pixel + offset) / escala

Ambos sensores deben quedar entre 0 y 1. Presets disponibles para el satélite:

| Preset | Escala | Offset |
| --- | --- | --- |
| Google Earth Engine (Escala 10000) | 10000 | 0   |
| Google Earth Engine (Reflectancia 0-1) | 1   | 0   |
| Sentinel-2 (L2A post-2022) | 10000 | -1000 |
| Sentinel-2 (L2A pre-2022) | 10000 | 0   |
| Landsat 8/9 (Collection 2 Level 2) | 36363.636 | -7272.727 |
| PlanetScope (SuperDove) | 10000 | 0   |
| Prisma (L2D), solo hiperespectral | 65535 | 0   |
| Personalizado | editable | editable |

Para el dron, la escala y el offset se ingresan a mano (por defecto 1 y 0).

> Si exporta Sentinel-2 desde Google Earth Engine con la colección armonizada (`S2_SR_HARMONIZED`), el offset ya viene corregido: use offset 0. El preset *post-2022* es para productos L2A descargados directamente de Copernicus.

### Configuración de bandas

Se ingresa el número de banda (comenzando en 1) de **azul, verde, rojo, red edge, NIR, SWIR 1 y SWIR 2**, según el orden en que están guardadas en el TIF. **Si el sensor no tiene una banda, se ingresa 0**, y los índices que dependan de ella no se calculan. Los valores por defecto son 1 a 5 para el dron y 1 a 7 para el satélite.

## Cómo funciona internamente

1. **Sistema de coordenadas:** los rasters y el vector se reproyectan al sistema del archivo maestro.
  
2. **Área común:** cada escena se recorta a la intersección entre dron, satélite y vector. Si no hay superposición, se informa un error.
  
3. **Remuestreo del dron:** a 2 m para el visor espacial, y a la resolución del satélite (ej. 10 m) para la comparación. También se conserva la resolución nativa.
  
4. **Muestreo:** en cada cobertura se sortean hasta 100 puntos aleatorios dentro de sus polígonos, ponderados por área, con semilla fija (resultados reproducibles). Se descartan los píxeles sin dato.
  
5. **Firmas:** promedio de la reflectancia de los puntos por banda y cobertura.
  
6. **Índices:** se calculan solo si existen las bandas necesarias.
  
  | Índice | Fórmula |
  | --- | --- |
  | NDVI | (NIR − Rojo) / (NIR + Rojo) |
  | NDWI | (Verde − NIR) / (Verde + NIR) |
  | MNDWI | (Verde − SWIR) / (Verde + SWIR) |
  | NDMI | (NIR − SWIR) / (NIR + SWIR) |
  | SAVI | 1.5 · (NIR − Rojo) / (NIR + Rojo + 0.5) |
  
  Para MNDWI y NDMI se usa SWIR 1, o SWIR 2 si no hay SWIR 1.
  
7. **Ajuste radiométrico:** regresión lineal `Satélite = a + b · Dron` sobre los puntos válidos en ambos sensores, por cobertura, por banda y global. Se requieren al menos 3 puntos por grupo. Se reportan estas métricas:
  
  | Métrica | Qué mide |
  | --- | --- |
  | n   | Puntos válidos en ambos sensores |
  | $R^2$, pendiente, intercepto | De la regresión `Sat = a + b · Dron`. Lo ideal es pendiente ≈ 1 e intercepto ≈ 0 |
  | Sesgo (Sat − Uas) | Promedio de la diferencia entre sensores. Indica si uno sobreestima al otro |
  | MAE | Error absoluto medio |
  | RMSE | Raíz del error cuadrático medio |
  
  Sesgo, MAE y RMSE se calculan contra la línea 1:1, en unidades de reflectancia (o del índice).
  

## Resultados

Cada escena tiene su pestaña con:

| Sección | Contenido |
| --- | --- |
| **Visor espacial** | Mapa interactivo, superficie por cobertura, y mapas en RGB, falso color, NDVI, NDWI, MNDWI, NDMI, SAVI y banda individual. En hiperespectral, un deslizador para recorrer las bandas. |
| **Firmas espectrales** | Curvas generales y por cobertura (dron nativo, dron a resolución del satélite y satélite). |
| **Estadística de índices** | Distribución por cobertura y sensor (violín + boxplot) y dispersión dron vs satélite. |
| **Ajuste radiométrico** | $R^2$ por cobertura, regresión global, regresiones por cobertura y por banda, y tablas de métricas (global, por cobertura, por banda y cobertura × banda). Con filtro de bandas. |

Con un archivo vectorial cargado se agrega la pestaña **Comparación global**: evolución de las firmas entre escenas, resumen de $R^2$, métricas por escena y evolución temporal de los índices.

### Descargas

* **Individuales:** cada gráfico tiene su botón de descarga en PNG, y cada *Centro de descargas* ofrece las tablas en CSV.
* **Todo en un ZIP:** el panel **Descargar todos los resultados (ZIP)**, en la parte superior de los resultados, reúne todo en un solo archivo. Se presiona *Preparar ZIP* y luego *Descargar ZIP*. En multiespectral hay una opción para incluir también los mapas de cada banda (más lento). El ZIP se organiza así:

    resultados_AAAAMMDD_HHMM.zip
    ├── LEEME.txt                       # parámetros de la corrida y glosario de métricas
    ├── escenas/<escena>/
    │   ├── mapas/                      # RGB, falso color, índices (y banda individual)
    │   ├── firmas/                     # firmas generales y por cobertura
    │   ├── indices/                    # distribución y dispersión dron vs satélite
    │   ├── ajuste_radiometrico/        # regresiones y R²
    │   └── datos/                      # CSV: firmas, correlaciones, índices, métricas, superficies
    └── global/
        ├── graficos/                   # evolución entre escenas, R² global, regresiones consolidadas
        └── datos/                      # CSV consolidados y métricas por escena

> En modo hiperespectral el ZIP incluye las firmas y tablas, pero no mapas por banda (pueden ser cientos).

### Cómo interpretar los resultados

* Un $R^2$ cercano a 1 indica que ambos sensores varían de forma muy parecida. Revise también la **línea 1:1**: un $R^2$ alto no detecta por sí solo un desfase o una diferencia de escala sistemática.
* El $R^2$ global y por cobertura agrupa todas las bandas, y las diferencias naturales entre bandas (ej. NIR vs azul) lo elevan. Para evaluar la calidad del dron, priorice las métricas **por banda** y el **RMSE**, la **pendiente** y el **sesgo**.
* El píxel satelital mezcla varias superficies. En coberturas heterogéneas es normal un $R^2$ menor y curvas satelitales más aplanadas (efecto de píxel mixto).

## Limitaciones conocidas

* **Configuración compartida:** la escala, el offset y la configuración de bandas son únicos para todas las escenas del proyecto. Se congelan al presionar *Ejecutar plataforma*: para aplicar cambios del panel lateral hay que volver a ejecutar.
* **Hiperespectral sin descripciones de banda:** si el TIF no trae descripciones, las bandas se llaman `Banda_N` y el eje X muestra el número de banda, aunque el título diga "nm".
* **Mapas base en línea:** sin internet, el análisis funciona, pero los mapas de contexto pueden quedar sin fondo.

## Solución de problemas

| Mensaje o síntoma | Causa y solución |
| --- | --- |
| *Error de coordenadas: el archivo principal utiliza grados geográficos* | Reproyecte el raster a un sistema métrico (ej. UTM) antes de cargarlo. |
| *Las áreas espaciales no se superponen* | Dron, satélite y vector no comparten territorio. Revise sus extensiones y sistemas de coordenadas. |
| *Se requiere al menos una imagen en la primera escena* | Cargue al menos un TIF en la escena 1. |
| Una cobertura no aparece en la regresión | Tiene menos de 3 puntos válidos en ambos sensores (polígono pequeño o fuera de la imagen). |
| `TypeError` en `st.plotly_chart(width=...)` | Streamlit es anterior a 1.51. Ejecute `pip install -U -r requirements.txt`. |
| No se pueden subir archivos grandes | Verifique que `config.toml` esté en `.streamlit/` y reinicie la aplicación. |
