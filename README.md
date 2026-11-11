# Plataforma de Validación Espectral y Multitemporal

Aplicación web (Streamlit) para **validar y calibrar de forma cruzada imágenes de dron (UAS) contra imágenes satelitales**, y para explorar datos hiperespectrales.

Los drones comerciales con sensores multiespectrales (MicaSense, Sentera, etc.) pueden entregar valores radiométricos con incertidumbre. Esta plataforma toma un sensor satelital (por ejemplo Sentinel-2) como referencia y cuantifica qué tan bien coinciden ambos sensores sobre las mismas coberturas, en una o varias fechas.

## Qué permite hacer

- **Dos modalidades de análisis**
  - **Multiespectral (dron vs satélite):** firmas espectrales, índices espectrales y regresión lineal entre sensores ($R^2$).
  - **Hiperespectral:** firma espectral continua por cobertura y explorador de bandas sobre el mapa.
- **Visor espacial** (se puede activar o desactivar) con mapa interactivo, superficie por cobertura (ha) y mapas en color real, falso color, índices y banda individual.
- **Análisis multitemporal:** hasta 10 escenas (fechas o campañas) y una pestaña de comparación global.
- **Métricas de concordancia:** además del $R^2$, pendiente, intercepto, sesgo, PBIAS, MAE, RMSE, NRMSE, NSE y KGE entre satélite y dron, con intervalos de confianza al 95% para la pendiente, el intercepto y el sesgo. Se calculan por escena, cobertura y banda.
- **Exportación:** cada gráfico en PNG de alta resolución (300 dpi) y cada tabla en CSV, o **todo junto en un único ZIP** con un solo clic.
- **Modo visor:** si no se carga un archivo vectorial, la plataforma funciona solo como visor espacial.

## Requisitos

- Python **3.10 o superior** (Linux o Windows)
- Conexión a internet para los mapas (Google Satélite en el mapa interactivo; Esri y OpenStreetMap en los mapas de contexto)

Las dependencias están en `requirements.txt`. Las principales son `streamlit`, `streamlit-folium`, `rasterio`, `geopandas`, `shapely`, `pyogrio`, `numpy`, `pandas`, `scipy`, `scikit-learn`, `plotly`, `matplotlib`, `matplotlib-scalebar`, `folium` y `contextily`. Las versiones mínimas fueron probadas, y también las versiones más recientes disponibles a octubre de 2026.

## Instalación y ejecución

Los pasos son los mismos en ambos sistemas: crear un entorno virtual, instalar las dependencias y ejecutar la aplicación. Cambian los comandos. No hace falta instalar GDAL aparte: `rasterio` y `geopandas` ya traen sus librerías en las versiones precompiladas.

Ubíquese primero en la carpeta del proyecto (la que contiene `app.py`).

### Linux (Ubuntu / Debian)

```bash
# 0. Verificar Python (debe ser 3.10 o superior) e instalar venv y pip si faltan
python3 --version
sudo apt update
sudo apt install -y python3 python3-venv python3-pip

# 1. Crear y activar el entorno virtual
python3 -m venv venv
source venv/bin/activate

# 2. Instalar las dependencias
pip install --upgrade pip
pip install -r requirements.txt

# 3. Ejecutar la aplicación
streamlit run app.py
```

En otras distribuciones, instale Python 3.10 o superior con el gestor de paquetes correspondiente (`dnf`, `pacman`, etc.). Para volver a usar la aplicación más adelante, basta con `source venv/bin/activate` y `streamlit run app.py`.

### Windows (10 / 11)

Instale Python 3.10 o superior desde [python.org](https://www.python.org/downloads/windows/) y marque la casilla **Add python.exe to PATH** durante la instalación. Luego, en **PowerShell** (o en el terminal de VS Code):

```powershell
# 0. Verificar Python (debe ser 3.10 o superior)
python --version

# 1. Crear y activar el entorno virtual
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Instalar las dependencias
python -m pip install --upgrade pip
pip install -r requirements.txt

# 3. Ejecutar la aplicación
streamlit run app.py
```

- Si PowerShell muestra el error *"la ejecución de scripts está deshabilitada en este sistema"*, ejecute una sola vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y vuelva a activar el entorno.
- Si prefiere el **Símbolo del sistema (cmd)**, active el entorno con `venv\Scripts\activate.bat`; el resto de los comandos es igual.
- Si `python` no se reconoce, pruebe con `py -m venv venv` (el lanzador de Python de Windows).
- Para volver a usar la aplicación más adelante, basta con `.\venv\Scripts\Activate.ps1` y `streamlit run app.py`.

### Abrir la aplicación

Al ejecutar `streamlit run app.py`, la aplicación se abre sola en el navegador en `http://localhost:8501`. Si no se abre, copie esa dirección en el navegador. Para detenerla, presione `Ctrl + C` en el terminal.

Para usar otro puerto: `streamlit run app.py --server.port 8502`.

## Estructura del proyecto

```
.
├── app.py                  # Aplicación completa
├── requirements.txt        # Dependencias
├── README.md
└── .streamlit/
    └── config.toml         # Configuración de Streamlit (límite de carga)
```

> **Importante:** `config.toml` debe estar dentro de la carpeta `.streamlit/` para que Streamlit lo lea. Define `server.maxUploadSize = 1000`, que permite cargar archivos de hasta 1000 MB.

## Guía de uso

Todo se configura en el panel lateral, de arriba hacia abajo:

1. **Modalidad de análisis:** *Multiespectral (dron/satélite)* o *Hiperespectral*.
2. **Archivo vectorial (opcional):** un `.zip` con el shapefile completo (`.shp`, `.shx`, `.dbf`, `.prj`) o un `.gpkg`. Si el `.gpkg` tiene varias capas, se elige cuál usar. Luego se elige la columna que identifica la cobertura de cada polígono (ej. agua, vegetación, suelo).
3. **Visor espacial:** casilla *Activar visor espacial* (activa por defecto). Si se desactiva, no se generan los mapas ni el mapa interactivo.
4. **Escenas:** cantidad de escenas (1 a 10) y, para cada una, el GeoTIFF del dron y/o del satélite. En hiperespectral solo se carga la imagen hiperespectral.
5. **Ajustes radiométricos:** preset del satélite (o *Personalizado*), nombre del sensor para los gráficos y escala/offset del dron.
6. **Configuración de bandas** (solo multiespectral): número de banda de cada color, para dron y satélite.
7. **Ejecutar plataforma.** Los resultados de cada escena se procesan al abrir su pestaña. **Reiniciar entorno** limpia la sesión.

### Datos de entrada

| Dato | Formato | Notas |
|---|---|---|
| Imágenes de dron y satélite | GeoTIFF (`.tif`) | Deben estar en un sistema **proyectado en metros** (ej. UTM). Se reproyectan automáticamente al sistema del primer archivo. |
| Cobertura (opcional) | `.zip` (shapefile) o `.gpkg` | Un atributo debe identificar la cobertura de cada polígono. Si el `.gpkg` tiene varias capas, la app permite elegir cuál usar. |
| Imagen hiperespectral | GeoTIFF multibanda | Si cada banda tiene una descripción con la longitud de onda (ej. `B450`), se usa como eje X. |

**Nombre de los archivos:** se recomienda `AAAA-MM-DD_Lugar_...tif`, por ejemplo `2025-07-15_Laguna-Verde_dron.tif`. De ahí se obtiene el título de la escena (*Laguna Verde (2025-07-15)*). Si el nombre no sigue este formato, se usa el nombre del archivo sin extensión.

> El primer archivo de la escena 1 (el del dron, o el del satélite si no hay dron) define el sistema de coordenadas de todo el proyecto. Si está en grados (geográfico), la plataforma se detiene con un error.

### Ajuste radiométrico

La reflectancia se calcula como:

```
reflectancia = (valor_del_pixel + offset) / escala
```

Ambos sensores deben quedar entre 0 y 1. Presets disponibles para el satélite:

| Preset | Escala | Offset |
|---|---|---|
| Google Earth Engine (Escala 10000) | 10000 | 0 |
| Google Earth Engine (Reflectancia 0-1) | 1 | 0 |
| Sentinel-2 (L2A post-2022) | 10000 | -1000 |
| Sentinel-2 (L2A pre-2022) | 10000 | 0 |
| Landsat 8/9 (Collection 2 Level 2) | 36363.636 | -7272.727 |
| PlanetScope (SuperDove) | 10000 | 0 |
| Prisma (L2D), solo hiperespectral | 65535 | 0 |
| Personalizado | editable | editable |

Por defecto se preselecciona *Sentinel-2 (L2A post-2022)* en multiespectral y *Prisma (L2D)* en hiperespectral. La escala y el offset del satélite solo se pueden editar con *Personalizado*. Para el dron, la escala y el offset se ingresan siempre a mano (por defecto 1 y 0).

El campo **Nombre en gráficos** es el nombre del satélite que aparece en leyendas y títulos. Se sugiere automáticamente según el preset.

> Si exporta Sentinel-2 desde Google Earth Engine con la colección armonizada (`S2_SR_HARMONIZED`), el offset ya viene corregido: use offset 0. El preset *post-2022* es para productos L2A descargados directamente de Copernicus.

### Configuración de bandas

Se ingresa el número de banda (comenzando en 1) de **azul, verde, rojo, red edge, NIR, SWIR 1 y SWIR 2**, según el orden en que están guardadas en el TIF. **Si el sensor no tiene una banda, se ingresa 0**, y los índices que dependan de ella no se calculan.

Valores por defecto:

| Sensor | Azul | Verde | Rojo | Red edge | NIR | SWIR 1 | SWIR 2 |
|---|---|---|---|---|---|---|---|
| Dron | 1 | 2 | 3 | 4 | 5 | 0 | 0 |
| Satélite | 1 | 2 | 3 | 4 | 5 | 6 | 7 |

Solo se comparan entre sensores las bandas que están configuradas en ambos.

## Cómo funciona internamente

1. **Sistema de coordenadas:** los rasters y el vector se reproyectan al sistema del archivo maestro.
2. **Área común:** cada escena se recorta a la intersección entre el satélite, el vector y la **huella real de datos del dron** (zona con datos válidos, no su rectángulo envolvente). Si no hay superposición, se informa un error.
3. **Remuestreo del dron:** se detecta su resolución nativa y se conserva.
   - *Visor espacial:* solo se reduce a 2 m si el dron es más fino que 2 m.
   - *Comparación con el satélite:* se lleva a la **grilla exacta del satélite**. Si el dron es más fino, se promedia; si ya tiene la misma resolución y está alineado, se usa sin suavizar; si tiene la misma resolución pero está desfasado, se realinea; y si es más grueso que el satélite, la app muestra un aviso para interpretar las métricas con cautela. El aviso aparece bajo el mapa interactivo.
   - Los datos del dron a resolución del satélite aparecen en los gráficos como `Uas (10m)`, aunque el satélite no sea de 10 m.
4. **Muestreo:** en cada cobertura se sortean hasta 100 puntos aleatorios dentro de sus polígonos, ponderados por área, con semilla fija (resultados reproducibles). Se descartan los píxeles sin dato.
5. **Firmas:** promedio de la reflectancia de los puntos por banda y cobertura.
6. **Índices:** se calculan solo si existen las bandas necesarias.

   | Índice | Fórmula |
   |---|---|
   | NDVI | (NIR − Rojo) / (NIR + Rojo) |
   | NDWI | (Verde − NIR) / (Verde + NIR) |
   | MNDWI | (Verde − SWIR) / (Verde + SWIR) |
   | NDMI | (NIR − SWIR) / (NIR + SWIR) |
   | SAVI | 1.5 · (NIR − Rojo) / (NIR + Rojo + 0.5) |

   Para MNDWI y NDMI se usa SWIR 1, o SWIR 2 si no hay SWIR 1.
7. **Ajuste radiométrico:** regresión lineal `Satélite = a + b · Dron` sobre los puntos válidos en ambos sensores (dron a resolución del satélite), por cobertura, por banda y global. Se requieren al menos 3 puntos por grupo. Se reportan estas métricas:

   | Métrica | Qué mide |
   |---|---|
   | n | Puntos válidos en ambos sensores |
   | $R^2$, pendiente, intercepto | De la regresión `Sat = a + b · Dron`. Lo ideal es pendiente ≈ 1 e intercepto ≈ 0 |
   | Sesgo (Sat − Uas) | Promedio de la diferencia entre sensores. Indica si uno sobreestima al otro |
   | PBIAS (%) | 100 · Σ(Sat − Dron) / ΣSat. Positivo = el dron subestima (mismo signo que el sesgo) |
   | MAE | Error absoluto medio |
   | RMSE | Raíz del error cuadrático medio |
   | NRMSE (%) | RMSE dividido por el rango del satélite. Es estable cuando la media es cercana a 0 (ej. NDWI) |
   | NSE | Nash-Sutcliffe, con el satélite como referencia. 1 es concordancia perfecta; ≤ 0 indica que el dron no mejora a la media del satélite |
   | KGE | Kling-Gupta (2009), con el satélite como referencia. 1 es concordancia perfecta |
   | IC95% | Intervalos de confianza de la pendiente, el intercepto (t de Student, n − 2 g.l.) y el sesgo (t de Student, n − 1 g.l.) |

   Sesgo, MAE y RMSE se calculan contra la línea 1:1, en unidades de reflectancia (o del índice). Si el intervalo de la pendiente incluye 1, o el del intercepto o el sesgo incluye 0, no hay evidencia de desviación respecto de la línea 1:1.

   > Los puntos se sortean dentro de los polígonos y pueden tener autocorrelación espacial, por lo que los intervalos de confianza son optimistas.

## Resultados

Cada escena tiene su pestaña con:

| Sección | Contenido |
|---|---|
| **Visor espacial** | Mapa interactivo (con los límites del satélite y del dron, y las coberturas), superficie por cobertura, y mapas en RGB, falso color, NDVI, NDWI, MNDWI, NDMI, SAVI y banda individual, cada uno con mapas de contexto regional y país. En hiperespectral, un deslizador para recorrer las bandas. |
| **Firmas espectrales** | Curvas generales y por cobertura (dron nativo, dron a resolución del satélite y satélite). El satélite tiene una vista completa (hasta SWIR) y otra recortada hasta NIR. |
| **Estadística de índices** | Distribución por cobertura y sensor (violín + boxplot), promedios por cobertura y dispersión dron vs satélite con su tabla de métricas. |
| **Ajuste radiométrico** | $R^2$ por cobertura, regresión global, regresiones por cobertura y por banda, y tablas de métricas (global, por cobertura, por banda y cobertura × banda). Con filtro de bandas. |

En hiperespectral, la pestaña de cada escena se llama **Análisis de firmas hiperespectrales** y reúne las firmas general y por cobertura.

Con un archivo vectorial cargado se agrega la pestaña **Comparación global**, con cuatro secciones en multiespectral:

- **Evolución UAS** y **Evolución satélite** (completa y recortada hasta NIR): firmas por cobertura a lo largo de las escenas.
- **Resumen de ajuste global ($R^2$):** $R^2$ por cobertura y escena, tablas de métricas por escena, escena × cobertura y escena × banda, y regresiones consolidadas. Con filtro de bandas.
- **Evolución fenológica (índices):** evolución temporal de cada índice.

En hiperespectral solo muestra la evolución de las firmas.

Los mapas se generan con una escala de colores ajustada entre los percentiles 2 y 98 de cada imagen. Cada escena recibe un color propio en los gráficos comparativos, asignado automáticamente.

### Descargas

- **Individuales:** cada gráfico tiene su botón de descarga en PNG, y cada *Centro de descargas* ofrece las tablas en CSV.
- **Todo en un ZIP:** el panel **Descargar todos los resultados (ZIP)**, en la parte superior de los resultados, reúne todo en un solo archivo. Se presiona *Preparar ZIP* y luego *Descargar ZIP*. En multiespectral hay una opción para incluir también los mapas de cada banda (más lento). El ZIP se organiza así:

```
resultados_AAAAMMDD_HHMM.zip
├── LEEME.txt                       # parámetros de la corrida y glosario de métricas
├── escenas/<escena>/
│   ├── mapas/                      # RGB, falso color, índices (y banda_individual/)
│   ├── firmas/                     # firmas generales y por_cobertura/
│   ├── indices/                    # distribución y dispersión dron vs satélite
│   ├── ajuste_radiometrico/        # R2_por_cobertura, Regresion_Global, por_cobertura/, por_banda/
│   └── datos/                      # CSV: firmas, correlaciones, índices, métricas, superficies
└── global/
    ├── graficos/                   # evolución entre escenas, R² global, regresiones consolidadas
    └── datos/                      # CSV consolidados y métricas por escena
```

Los CSV de `datos/` de cada escena incluyen `firmas`, `correlacion_bandas`, `indices`, `correlacion_indices`, `superficie_por_cobertura` (en m² y ha) y las métricas global, por cobertura, por banda, cobertura × banda y por índice. En `global/datos/` están las firmas, correlaciones e índices de todas las escenas, y las métricas por escena, escena × cobertura y escena × banda.

> En modo hiperespectral el ZIP incluye las firmas y tablas, pero no mapas por banda (pueden ser cientos).

### Cómo interpretar los resultados

- Un $R^2$ cercano a 1 indica que ambos sensores varían de forma muy parecida. Revise también la **línea 1:1**: un $R^2$ alto no detecta por sí solo un desfase o una diferencia de escala sistemática.
- El $R^2$ global y por cobertura agrupa todas las bandas, y las diferencias naturales entre bandas (ej. NIR vs azul) lo elevan. Para evaluar la calidad del dron, priorice las métricas **por banda** y **cobertura × banda**, y dentro de ellas el **RMSE**, la **pendiente**, el **sesgo**, el **NSE** y el **KGE**.
- El píxel satelital mezcla varias superficies. En coberturas heterogéneas es normal un $R^2$ menor y curvas satelitales más aplanadas (efecto de píxel mixto).

## Limitaciones conocidas

- **Configuración compartida:** la escala, el offset y la configuración de bandas son únicos para todas las escenas del proyecto. Se congelan al presionar *Ejecutar plataforma*: para aplicar cambios del panel lateral hay que volver a ejecutar.
- **Hiperespectral sin descripciones de banda:** si el TIF no trae descripciones con la longitud de onda, las bandas se llaman `Banda_N` y el eje X muestra el número de banda en lugar de nanómetros.
- **Hiperespectral:** no calcula índices ni regresiones. Se omiten las bandas con reflectancia nula o igual a 0 en la firma.
- **Banda individual (multiespectral):** el selector ofrece las bandas 1 a 7.
- **Valores sin dato:** en los mapas, los píxeles con valor menor o igual a 0 se consideran sin dato.
- **Mapas en línea:** el mapa interactivo usa Google Satélite como fondo, y los mapas de contexto regional y país descargan su fondo de Esri (con respaldo en OpenStreetMap en el regional) una sola vez por escena. Sin internet, el análisis funciona, pero esos mapas muestran el aviso "Mapa base no disponible". Tras un fallo, la app no reintenta durante 5 minutos.

## Solución de problemas

| Mensaje o síntoma | Causa y solución |
|---|---|
| *Error de coordenadas: el archivo principal utiliza grados geográficos* | Reproyecte el raster a un sistema métrico (ej. UTM) antes de cargarlo. |
| *Las áreas espaciales no se superponen* | Dron (zona con datos), satélite y vector no comparten territorio. Revise sus extensiones y sistemas de coordenadas. |
| *El raster no tiene píxeles con datos válidos* | El dron no tiene datos válidos: todos sus píxeles son nodata o 0. Revise el archivo. |
| *Se requiere al menos una imagen en la primera escena* | Cargue al menos un TIF en la escena 1. |
| *Atención: el dron es más grueso que el satélite* | Aviso, no un error. No hay detalle extra para comparar, así que interprete las métricas con cautela. |
| Una cobertura no aparece en la regresión | Tiene menos de 3 puntos válidos en ambos sensores (polígono pequeño o fuera de la imagen). |
| `TypeError` en `st.plotly_chart(width=...)` | Streamlit es anterior a 1.51. Ejecute `pip install -U -r requirements.txt`. |
| `python3 -m venv` falla en Linux (*ensurepip is not available*) | Falta el paquete de venv: `sudo apt install python3-venv`. |
| PowerShell no deja activar el entorno (Windows) | Ejecute `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` o use el Símbolo del sistema con `venv\Scripts\activate.bat`. |
| `streamlit` no se reconoce como comando | El entorno virtual no está activo, o use `python -m streamlit run app.py`. |
| El puerto 8501 está ocupado | Use otro puerto: `streamlit run app.py --server.port 8502`. |
| No se pueden subir archivos grandes | Verifique que `config.toml` esté en `.streamlit/` y reinicie la aplicación. |
| No se pudo generar el ZIP | Vuelva a presionar *Preparar ZIP*. Si persiste, desmarque la opción de mapas de banda individual. |
