# -*- coding: utf-8 -*-
import streamlit as st
import rasterio
from rasterio.io import MemoryFile
import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.mask import mask
import tempfile, zipfile, os, re, io
import base64
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.transform import from_bounds
import rasterio.windows
import folium
from streamlit_folium import st_folium
import plotly.express as px
import plotly.graph_objects as go
import random
from shapely.geometry import Point, box
import matplotlib.pyplot as plt
from matplotlib_scalebar.scalebar import ScaleBar
import contextily as cx

st.set_page_config(page_title="Visualizador de datos espaciales y multitemporales", layout="wide")
st.title("Visualizador de datos espaciales y multitemporales")

# -----------------------------
# 1. Funciones principales y de interfaz personalizadas
# -----------------------------
def custom_download_button(data, filename, text="Descargar imagen", mime="image/png"):
    """
    Botón de descarga HTML puro (Base64) que evita el re-run completo de Streamlit.
    """
    b64 = base64.b64encode(data).decode()
    href = f'data:{mime};base64,{b64}'
    button_html = f"""
    <a href="{href}" download="{filename}" style="
        display: block; width: 100%; text-align: center; padding: 0.5rem 1rem;
        background-color: #ffffff; color: #31333F; border: 1px solid #d5d9e0;
        border-radius: 0.5rem; text-decoration: none; font-family: sans-serif;
        font-size: 1rem; transition: all 0.2s ease-in-out; margin-bottom: 1rem;
    " onmouseover="this.style.borderColor='#FF4B4B'; this.style.color='#FF4B4B'" 
       onmouseout="this.style.borderColor='#d5d9e0'; this.style.color='#31333F'">
       {text}
    </a>
    """
    st.markdown(button_html, unsafe_allow_html=True)

@st.cache_data
def process_vector_file(uploaded_file):
    if uploaded_file.name.endswith('.zip'):
        temp_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(uploaded_file, 'r') as z:
            z.extractall(temp_dir)
        for root, _, files in os.walk(temp_dir):
            for f in files:
                if f.endswith(".shp"):
                    return os.path.join(root, f)
    elif uploaded_file.name.endswith('.gpkg') or uploaded_file.name.endswith('.GPKG'):
        temp_gpkg = tempfile.NamedTemporaryFile(delete=False, suffix=".gpkg")
        temp_gpkg.write(uploaded_file.getvalue())
        temp_gpkg.close()
        return temp_gpkg.name
    return None

@st.cache_data
def load_vector_preview(vector_file):
    path = process_vector_file(vector_file)
    return gpd.read_file(path)

def calcular_regresion_limpia(df_sub):
    X = df_sub[['Uas']] 
    y = df_sub['Sat']
    model = LinearRegression()
    model.fit(X, y)
    r2 = r2_score(y, model.predict(X))
    return model, r2

@st.cache_data
def reproject_raster(in_path, target_crs_str):
    target_crs = rasterio.crs.CRS.from_string(target_crs_str)
    with rasterio.open(in_path) as src:
        if src.crs == target_crs: return in_path 
        transform, width, height = calculate_default_transform(src.crs, target_crs, src.width, src.height, *src.bounds)
        kwargs = src.meta.copy()
        kwargs.update({"crs": target_crs, "transform": transform, "width": width, "height": height, "compress": 'lzw', "tiled": True})
        reproj_path = tempfile.NamedTemporaryFile(delete=False, suffix=".tif").name
        with rasterio.open(reproj_path, "w", **kwargs) as dst:
            for i in range(1, src.count + 1):
                reproject(source=rasterio.band(src, i), destination=rasterio.band(dst, i),
                          src_transform=src.transform, src_crs=src.crs, dst_transform=transform, dst_crs=target_crs,
                          resampling=Resampling.bilinear)
            dst.descriptions = src.descriptions
    return reproj_path

@st.cache_data
def resample_raster(in_path, target_res=2.0): 
    with rasterio.open(in_path) as src:
        if src.crs.is_geographic:
            raise ValueError("Error de sistema de coordenadas: el raster está en coordenadas geográficas (grados). Utilice un sistema proyectado (ej. utm).")
        new_width = max(int((src.bounds.right - src.bounds.left) / target_res), 1)
        new_height = max(int((src.bounds.top - src.bounds.bottom) / target_res), 1)
        new_transform = from_bounds(*src.bounds, new_width, new_height)
        kwargs = src.meta.copy()
        kwargs.update({'transform': new_transform, 'width': new_width, 'height': new_height, 'compress': 'lzw', 'tiled': True})
        out_path = tempfile.NamedTemporaryFile(delete=False, suffix=".tif").name
        with rasterio.open(out_path, 'w', **kwargs) as dst:
            for i in range(1, src.count + 1):
                reproject(source=rasterio.band(src, i), destination=rasterio.band(dst, i),
                          src_transform=src.transform, src_crs=src.crs, dst_transform=new_transform, dst_crs=src.crs,
                          resampling=Resampling.bilinear)
            dst.descriptions = src.descriptions
    return out_path

def add_cartographic_elements(ax, crs_is_metric, title):
    ax.set_title(title, pad=20, fontsize=14, color='black', weight='bold')
    ax.tick_params(axis='both', colors='black', labelsize=8)
    for spine in ax.spines.values(): spine.set_color('black')
    ax.grid(color='black', linestyle='--', linewidth=0.5, alpha=0.2)
    ax.set_xlabel('Este (x)', color='black', fontsize=10)
    ax.set_ylabel('Norte (y)', color='black', fontsize=10)
    if crs_is_metric:
        scalebar = ScaleBar(1, "m", length_fraction=0.2, location="lower right", color="black", box_color="white", box_alpha=0.8)
        ax.add_artist(scalebar)
    ax.text(0.05, 0.95, 'N\n↑', transform=ax.transAxes, color='black', fontsize=16, ha='center', va='center', weight='bold', bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=2))

def create_context_maps(ax_regional, ax_national, main_gdf, raster_bounds=None, raster_crs=None):
    if main_gdf is not None and not main_gdf.empty: gdf_wm = main_gdf.to_crs(epsg=3857)
    elif raster_bounds is not None and raster_crs is not None:
        xmin, xmax, ymin, ymax = raster_bounds
        dummy_gdf = gpd.GeoDataFrame({'geometry': [box(xmin, ymin, xmax, ymax)]}, crs=raster_crs)
        gdf_wm = dummy_gdf.to_crs(epsg=3857)
    else: return

    gdf_wm.plot(ax=ax_regional, facecolor='none', edgecolor='red', linewidth=2)
    try:
        minx, miny, maxx, maxy = gdf_wm.total_bounds
        cx_coord, cy_coord = (minx + maxx) / 2, (miny + maxy) / 2
        buffer_reg = 15000
        ax_regional.set_xlim(cx_coord - buffer_reg, cx_coord + buffer_reg)
        ax_regional.set_ylim(cy_coord - buffer_reg, cy_coord + buffer_reg)
        cx.add_basemap(ax_regional, source=cx.providers.OpenStreetMap.Mapnik, alpha=0.7)
    except Exception: pass

    centroid = gdf_wm.centroid
    centroid.plot(ax=ax_national, color='red', marker='*', markersize=250, edgecolor='black', linewidth=1.5, zorder=5)
    try:
        buffer_nat = 800000
        ax_national.set_xlim(cx_coord - buffer_nat, cx_coord + buffer_nat)
        ax_national.set_ylim(cy_coord - buffer_nat, cy_coord + buffer_nat)
        cx.add_basemap(ax_national, source=cx.providers.CartoDB.Positron, alpha=0.9)
    except Exception: pass

    for ax_map, title in zip([ax_regional, ax_national], ["Contexto regional", "Contexto país"]):
        ax_map.set_xticks([])
        ax_map.set_yticks([])
        for spine in ax_map.spines.values():
            spine.set_edgecolor('black')
            spine.set_linewidth(1.5)
        ax_map.set_title(title, fontsize=11, weight='bold', color='black', pad=10)

def parse_scene_name(filename):
    match = re.search(r'^(\d{4}-\d{2}-\d{2})_([^_]+)', filename)
    if match:
        fecha = match.group(1)
        lugar = match.group(2).replace('-', ' ').title()
        return f"{lugar} ({fecha})"
    return os.path.splitext(filename)[0]

# --- BANDAS DE GUÍA Y EXPORTACIÓN ---
def add_spectral_bands_plotly(fig):
    regiones = [(450, 495, "blue", "Azul"), (495, 570, "green", "Verde"), (620, 750, "red", "Rojo"),
                (750, 1400, "gray", "Nir"), (1400, 1800, "orange", "Swir 1"), (1900, 2500, "brown", "Swir 2")]
    for x0, x1, color, nombre in regiones:
        fig.add_vrect(x0=x0, x1=x1, fillcolor=color, opacity=0.06, layer="below", line_width=0,
                      annotation_text=nombre, annotation_position="top left", annotation_font_color=color, annotation_font_size=10)

def add_spectral_bands_plt(ax):
    ymin, ymax = ax.get_ylim()
    regiones = [(450, 495, "blue", "Azul"), (495, 570, "green", "Verde"), (620, 750, "red", "Rojo"),
                (750, 1400, "gray", "Nir"), (1400, 1800, "orange", "Swir 1"), (1900, 2500, "brown", "Swir 2")]
    for x0, x1, color, nombre in regiones:
        ax.axvspan(x0, x1, color=color, alpha=0.06, lw=0, zorder=0)
        ax.text((x0+x1)/2, ymax - (ymax-ymin)*0.02, nombre, color=color, ha='center', va='top', fontsize=8, alpha=0.8, weight='bold', zorder=1)
    ax.set_ylim(ymin, ymax)

def export_formal_signature(df, cob, sat_name, tipo_datos, color_map, y_min, y_max, titulo_extra=""):
    fig, ax = plt.subplots(figsize=(8, 5), dpi=300)
    sensores = df['Sensor'].unique() if 'Sensor' in df.columns else ['Escena Global']
    
    if 'Escena' in df.columns: 
        escenas = df['Escena'].unique()
        for escena in escenas:
            df_e = df[df['Escena'] == escena].copy()
            df_e['Wavelength'] = df_e['Banda'].astype(str).str.extract(r'(\d+)').astype(float)
            if not df_e['Wavelength'].isnull().all():
                df_e = df_e.sort_values('Wavelength')
                ax.plot(df_e['Wavelength'], df_e['Reflectancia'], label=escena, linewidth=2)
            else:
                ax.plot(df_e['Banda'], df_e['Reflectancia'], label=escena, marker='o', linewidth=2)
    else: 
        for sensor in sensores:
            df_s = df[df['Sensor'] == sensor].copy()
            if tipo_datos == "Multiespectral (dron/satélite)":
                c = {'Uas (10m)': '#1f77b4', 'Uas (nativo)': '#2ca02c', sat_name: '#8c564b'}.get(sensor, 'black')
                ax.plot(df_s['Banda'], df_s['Reflectancia'], marker='o', color=c, label=sensor, linewidth=2)
            else:
                c = color_map.get(cob, '#8c564b')
                df_s['Wavelength'] = df_s['Banda'].astype(str).str.extract(r'(\d+)').astype(float)
                if not df_s['Wavelength'].isnull().all():
                    df_s = df_s.sort_values('Wavelength')
                    ax.plot(df_s['Wavelength'], df_s['Reflectancia'], color=c, label=cob, linewidth=2)
                else:
                    if 'idx_real' in df_s.columns: df_s = df_s.sort_values('idx_real')
                    ax.plot(df_s['Banda'], df_s['Reflectancia'], color=c, label=cob, linewidth=2)

    ax.set_ylim([y_min, y_max])
    if tipo_datos != "Multiespectral (dron/satélite)": add_spectral_bands_plt(ax)
    
    titulo = f"Evolución: {cob} {titulo_extra}" if 'Escena' in df.columns else f"Firma espectral: {cob} {titulo_extra}"
    ax.set_title(titulo, fontsize=14, weight='bold', pad=15)
    ax.set_xlabel("Longitud de onda (nm)" if tipo_datos != "Multiespectral (dron/satélite)" else "Banda espectral", fontsize=12)
    ax.set_ylabel("Reflectancia", fontsize=12)
    ax.grid(color='gray', linestyle=':', linewidth=0.5, alpha=0.7)
    ax.legend(frameon=True, facecolor='white', edgecolor='black', bbox_to_anchor=(1.05, 1) if 'Escena' in df.columns else None, loc='upper left' if 'Escena' in df.columns else 'best')
    for spine in ax.spines.values(): spine.set_color('black'); spine.set_linewidth(1.2)
    plt.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png", bbox_inches='tight'); plt.close(fig); return buf.getvalue()

def export_formal_general(df, sensor_name, tipo_datos, color_map, y_min, y_max):
    fig, ax = plt.subplots(figsize=(8, 5), dpi=300)
    cobs = df['Cobertura'].unique()
    for cob in cobs:
        df_c = df[df['Cobertura'] == cob].copy()
        color_cob = color_map.get(cob, 'black')
        if tipo_datos == "Multiespectral (dron/satélite)":
            ax.plot(df_c['Banda'], df_c['Reflectancia'], marker='o', label=cob, color=color_cob, linewidth=2)
        else:
            df_c['Wavelength'] = df_c['Banda'].astype(str).str.extract(r'(\d+)').astype(float)
            if not df_c['Wavelength'].isnull().all():
                df_c = df_c.sort_values('Wavelength')
                ax.plot(df_c['Wavelength'], df_c['Reflectancia'], label=cob, color=color_cob, linewidth=2)
            else:
                if 'idx_real' in df_c.columns: df_c = df_c.sort_values('idx_real')
                ax.plot(df_c['Banda'], df_c['Reflectancia'], label=cob, color=color_cob, linewidth=2)
    
    ax.set_ylim([y_min, y_max])
    if tipo_datos != "Multiespectral (dron/satélite)": add_spectral_bands_plt(ax)
    ax.set_title(f"Firmas espectrales: {sensor_name}", fontsize=14, weight='bold', pad=15)
    ax.set_xlabel("Longitud de onda (nm)" if tipo_datos != "Multiespectral (dron/satélite)" else "Banda espectral", fontsize=12)
    ax.set_ylabel("Reflectancia", fontsize=12)
    ax.grid(color='gray', linestyle=':', linewidth=0.5, alpha=0.7)
    ax.legend(frameon=True, facecolor='white', edgecolor='black', bbox_to_anchor=(1.05, 1), loc='upper left')
    for spine in ax.spines.values(): spine.set_color('black'); spine.set_linewidth(1.2)
    plt.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png", bbox_inches='tight'); plt.close(fig); return buf.getvalue()

def export_formal_boxplot(df, idx_name, sat_name):
    fig, ax = plt.subplots(figsize=(8, 5), dpi=300)
    sensores = sorted(df['Sensor'].unique())
    coberturas = sorted(df['Cobertura'].unique())
    positions, data_list, colors = [], [], []
    color_map = {'Uas (10m)': '#1f77b4', 'Uas (nativo)': '#2ca02c', sat_name: '#8c564b'}
    base_pos = 1; tick_pos = []
    
    for cob in coberturas:
        group_pos = []
        for sens in sensores:
            vals = df[(df['Cobertura'] == cob) & (df['Sensor'] == sens)]['Valor'].dropna().values
            if len(vals) > 0:
                data_list.append(vals)
                positions.append(base_pos)
                group_pos.append(base_pos)
                colors.append(color_map.get(sens, 'gray'))
                base_pos += 1
        if group_pos: tick_pos.append(np.mean(group_pos))
        base_pos += 1

    if data_list:
        bplot = ax.boxplot(data_list, positions=positions, patch_artist=True, widths=0.6,
                           boxprops=dict(facecolor="white", color="black"),
                           medianprops=dict(color="red", linewidth=1.5),
                           whiskerprops=dict(color="black", linewidth=1.5),
                           capprops=dict(color="black", linewidth=1.5),
                           flierprops=dict(marker='o', color='black', alpha=0.5))
        for patch, color in zip(bplot['boxes'], colors):
            patch.set_facecolor(color); patch.set_alpha(0.7)
        ax.set_xticks(tick_pos); ax.set_xticklabels(coberturas, rotation=45, ha='right')
        from matplotlib.patches import Patch
        legend_elements = [Patch(facecolor=color_map.get(s, 'gray'), edgecolor='black', label=s) for s in sensores]
        ax.legend(handles=legend_elements, frameon=True, facecolor='white', edgecolor='black')

    ax.set_title(f"Distribución estadística: {idx_name}", fontsize=14, weight='bold', pad=15)
    ax.set_ylabel("Valor del índice", fontsize=12)
    ax.grid(color='gray', linestyle=':', linewidth=0.5, alpha=0.7, axis='y')
    for spine in ax.spines.values(): spine.set_color('black'); spine.set_linewidth(1.2)
    plt.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png", bbox_inches='tight'); plt.close(fig); return buf.getvalue()

def export_formal_scatter(df, title, r2_val, es_indice=False):
    fig, ax = plt.subplots(figsize=(6, 5), dpi=300)
    color_col = 'Escena' if 'Escena' in df.columns else ('Cobertura' if es_indice else ('Banda' if 'Banda' in df.columns and len(df['Banda'].unique()) > 1 else None))
    
    if color_col:
        cmap = plt.get_cmap('tab10')
        groups = df[color_col].unique()
        colors = [cmap(i % 10) for i in range(len(groups))]
        for i, grp in enumerate(groups):
            df_g = df[df[color_col] == grp]
            ax.scatter(df_g['Uas'], df_g['Sat'], label=grp, color=colors[i], alpha=0.8, s=40)
    else:
        ax.scatter(df['Uas'], df['Sat'], color='#1f77b4', alpha=0.8, s=40)

    mod = LinearRegression().fit(df[['Uas']], df['Sat'])
    x_vals = pd.DataFrame({'Uas': [df['Uas'].min(), df['Uas'].max()]})
    y_vals = mod.predict(x_vals)
    ax.plot(x_vals['Uas'], y_vals, color='black', linestyle='--', linewidth=2, label=f'Tendencia (r²={r2_val:.3f})')

    ax.set_title(title, fontsize=14, weight='bold', pad=15)
    ax.set_xlabel("Valor UAS", fontsize=12)
    ax.set_ylabel("Valor Satélite", fontsize=12)
    ax.grid(color='gray', linestyle=':', linewidth=0.5, alpha=0.7)
    ax.legend(frameon=True, facecolor='white', edgecolor='black')
    for spine in ax.spines.values(): spine.set_color('black'); spine.set_linewidth(1.2)
    plt.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png", bbox_inches='tight'); plt.close(fig); return buf.getvalue()

# -----------------------------
# 2. Motor de procesamiento
# -----------------------------
def inicializar_base(uas_file, sat_file, master_crs, master_gdf, col_clase, tipo_datos):
    data = {'has_sat': sat_file is not None, 'has_uas': uas_file is not None, 'tipo_datos': tipo_datos}
    sat_path_temp = None; uas_path_temp = None
    geometrias_interseccion = []
    sat_bound_orig = None; uas_bound_orig = None

    if data['has_sat']:
        t_sat = tempfile.NamedTemporaryFile(delete=False, suffix=".tif")
        t_sat.write(sat_file.getvalue()); t_sat.close()
        sat_path_temp = reproject_raster(t_sat.name, master_crs.to_string())
        with rasterio.open(sat_path_temp) as src:
            sat_bound_orig = box(*src.bounds)
            geometrias_interseccion.append(sat_bound_orig)

    if data['has_uas']:
        t_uas = tempfile.NamedTemporaryFile(delete=False, suffix=".tif")
        t_uas.write(uas_file.getvalue()); t_uas.close()
        uas_path_temp = reproject_raster(t_uas.name, master_crs.to_string())
        with rasterio.open(uas_path_temp) as src:
            uas_bound_orig = box(*src.bounds)
            geometrias_interseccion.append(uas_bound_orig)

    if master_gdf is not None and not master_gdf.empty:
        geometrias_interseccion.append(box(*master_gdf.total_bounds))

    caja_comun = geometrias_interseccion[0]
    for geom in geometrias_interseccion[1:]:
        caja_comun = caja_comun.intersection(geom)

    if caja_comun.is_empty: raise ValueError("Las áreas espaciales no se superponen.")

    data['bounds_sat_orig'] = gpd.GeoDataFrame(geometry=[sat_bound_orig], crs=master_crs).to_crs(epsg=4326) if sat_bound_orig else None
    data['bounds_uas_orig'] = gpd.GeoDataFrame(geometry=[uas_bound_orig], crs=master_crs).to_crs(epsg=4326) if uas_bound_orig else None
    data['caja_interseccion_wgs84'] = gpd.GeoDataFrame(geometry=[caja_comun], crs=master_crs).to_crs(epsg=4326)

    def recortar_a_caja(path, geom):
        with rasterio.open(path) as src:
            out_image, out_transform = mask(src, [geom], crop=True)
            out_meta = src.meta.copy()
            out_meta.update({"height": out_image.shape[1], "width": out_image.shape[2], "transform": out_transform})
            desc = src.descriptions
        out_p = tempfile.NamedTemporaryFile(delete=False, suffix=".tif").name
        with rasterio.open(out_p, "w", **out_meta) as dest:
            dest.write(out_image); dest.descriptions = desc
        return out_p

    if data['has_sat']: data['sat_clip_path'] = recortar_a_caja(sat_path_temp, caja_comun)
    if data['has_uas']: data['uas_path_raw'] = recortar_a_caja(uas_path_temp, caja_comun)

    if data['has_uas']:
        if tipo_datos == "Multiespectral (dron/satélite)":
            data['uas_path_1m'] = resample_raster(data['uas_path_raw'], target_res=2.0)
            data['uas_path_10m'] = resample_raster(data['uas_path_raw'], target_res=10.0)
        else:
            data['uas_path_1m'] = data['uas_path_raw']
            data['uas_path_10m'] = data['uas_path_raw']

    if master_gdf is not None:
        gdf_cortado = gpd.clip(master_gdf, caja_comun)
        if not gdf_cortado.empty:
            if gdf_cortado.crs.is_geographic: gdf_area = gdf_cortado.to_crs(epsg=3857)
            else: gdf_area = gdf_cortado.copy()
            gdf_cortado['area_m2'] = gdf_area.geometry.area
            data['gdf'] = gdf_cortado
            data['gdf_diss'] = gdf_cortado.dissolve(by=col_clase, aggfunc={'area_m2': 'sum'}).reset_index()
        else:
            data['gdf'] = None; data['gdf_diss'] = None
    else:
        data['gdf'] = None; data['gdf_diss'] = None

    return data

def calcular_firmas(data_dict, col_clase, sat_scale, sat_offset, uas_scale, uas_offset, bandas_config, sat_name):
    random.seed(42); np.random.seed(42)
    resultados, datos_correlacion, datos_indices, datos_corr_idx = [], [], [], []
    band_names_sat_map = {}; sat_idx_map = {}; bandas_comunes = set()
    band_names_uas_map = {}; uas_idx_map = {}

    if data_dict['tipo_datos'] == "Multiespectral (dron/satélite)":
        b_idx, g_idx, r_idx, re_idx, n_idx, swir1_idx, swir2_idx = bandas_config['uas']
        s_b_idx, s_g_idx, s_r_idx, s_re_idx, s_n_idx, s_swir1_idx, s_swir2_idx = bandas_config['sat']

        uas_bands = {name for idx, name in [(b_idx, "Azul"), (g_idx, "Verde"), (r_idx, "Rojo"), (re_idx, "Red edge"), (n_idx, "Nir"), (swir1_idx, "Swir 1"), (swir2_idx, "Swir 2")] if idx > 0}
        sat_bands = {name for idx, name in [(s_b_idx, "Azul"), (s_g_idx, "Verde"), (s_r_idx, "Rojo"), (s_re_idx, "Red edge"), (s_n_idx, "Nir"), (s_swir1_idx, "Swir 1"), (s_swir2_idx, "Swir 2")] if idx > 0}
        bandas_comunes = uas_bands.intersection(sat_bands) if data_dict['has_sat'] and data_dict['has_uas'] else set()

        uas_idx_map = {name: idx - 1 for idx, name in [(b_idx, "Azul"), (g_idx, "Verde"), (r_idx, "Rojo"), (re_idx, "Red edge"), (n_idx, "Nir"), (swir1_idx, "Swir 1"), (swir2_idx, "Swir 2")] if idx > 0}
        sat_idx_map = {name: idx - 1 for idx, name in [(s_b_idx, "Azul"), (s_g_idx, "Verde"), (s_r_idx, "Rojo"), (s_re_idx, "Red edge"), (s_n_idx, "Nir"), (s_swir1_idx, "Swir 1"), (s_swir2_idx, "Swir 2")] if idx > 0}
        band_names_uas_map = {idx: name for idx, name in [(b_idx, "Azul"), (g_idx, "Verde"), (r_idx, "Rojo"), (re_idx, "Red edge"), (n_idx, "Nir"), (swir1_idx, "Swir 1"), (swir2_idx, "Swir 2")] if idx > 0}
        band_names_sat_map = {idx: name for idx, name in [(s_b_idx, "Azul"), (s_g_idx, "Verde"), (s_r_idx, "Rojo"), (s_re_idx, "Red edge"), (s_n_idx, "Nir"), (s_swir1_idx, "Swir 1"), (s_swir2_idx, "Swir 2")] if idx > 0}
    else:
        if data_dict['has_sat']:
            with rasterio.open(data_dict['sat_clip_path']) as src:
                for i in range(src.count):
                    desc = src.descriptions[i] if src.descriptions and src.descriptions[i] else f"Banda_{i+1}"
                    band_names_sat_map[i + 1] = desc

    uas_10m_src = rasterio.open(data_dict['uas_path_10m']) if data_dict['has_uas'] else None
    uas_raw_src = rasterio.open(data_dict['uas_path_raw']) if data_dict['has_uas'] else None
    sat_src = rasterio.open(data_dict['sat_clip_path']) if data_dict['has_sat'] else None

    nodata_uas_raw = uas_raw_src.nodata if uas_raw_src else None
    nodata_uas_10m = uas_10m_src.nodata if uas_10m_src else None
    nodata_sat = sat_src.nodata if sat_src else None
    clases = sorted(data_dict['gdf'][col_clase].unique())

    def calc_idx_array(m, idx_map):
        def get_b(name):
            i = idx_map.get(name)
            return m[:, i] if i is not None and i < m.shape[1] else None
        res = {}
        R, G, N, SW1, SW2 = get_b("Rojo"), get_b("Verde"), get_b("Nir"), get_b("Swir 1"), get_b("Swir 2")
        SW = SW1 if SW1 is not None else SW2
        with np.errstate(divide='ignore', invalid='ignore'):
            if N is not None and R is not None: res['Ndvi'] = (N - R) / (N + R + 1e-6)
            if G is not None and N is not None: res['Ndwi'] = (G - N) / (G + N + 1e-6)
            if G is not None and SW is not None: res['Mndwi'] = (G - SW) / (G + SW + 1e-6)
            if N is not None and SW is not None: res['Ndmi'] = (N - SW) / (N + SW + 1e-6)
            if N is not None and R is not None: res['Savi'] = ((N - R) / (N + R + 0.5)) * 1.5
        return res

    def extraer_indices(muestras, idx_map, sensor_name, clase):
        recs = []
        if muestras is None or len(muestras) == 0: return recs
        res = calc_idx_array(muestras, idx_map)
        for idx_name, vals in res.items():
            for val in vals:
                if not np.isnan(val): recs.append({'Cobertura': clase, 'Sensor': sensor_name, 'Índice': idx_name, 'Valor': val})
        return recs

    for clase_actual in clases:
        polys = data_dict['gdf'][data_dict['gdf'][col_clase] == clase_actual]['geometry'].values
        areas = np.array([p.area for p in polys])
        total_area = areas.sum()
        if total_area == 0: continue
        probs = areas / total_area

        pts = []
        intentos = 0
        while len(pts) < 100 and intentos < 2000:
            chosen_poly = np.random.choice(polys, p=probs)
            bbox = chosen_poly.bounds
            p = Point(random.uniform(bbox[0], bbox[2]), random.uniform(bbox[1], bbox[3]))
            if p.within(chosen_poly): pts.append(p)
            intentos += 1

        if not pts: continue
        coordenadas = [(pt.x, pt.y) for pt in pts]
        m_uas_filt, m_sat_filt = None, None

        if uas_raw_src and data_dict['tipo_datos'] == "Multiespectral (dron/satélite)":
            m_uas_nat_crudo = np.array(list(uas_raw_src.sample(coordenadas))).astype(float)
            if nodata_uas_raw is not None: m_uas_nat_crudo[m_uas_nat_crudo == nodata_uas_raw] = np.nan
            m_uas_nat = (m_uas_nat_crudo + uas_offset) / uas_scale
            firma_uas_nat = np.nanmean(m_uas_nat, axis=0)
            for b in range(uas_raw_src.count):
                if (b + 1) in band_names_uas_map:
                    resultados.append({'Cobertura': clase_actual, 'Banda': band_names_uas_map[b + 1], 'Sensor': 'Uas (nativo)', 'Reflectancia': firma_uas_nat[b]})
            datos_indices.extend(extraer_indices(m_uas_nat, uas_idx_map, 'Uas (nativo)', clase_actual))

        if uas_10m_src and data_dict['tipo_datos'] == "Multiespectral (dron/satélite)":
            m_uas_10m_crudo = np.array(list(uas_10m_src.sample(coordenadas))).astype(float)
            if nodata_uas_10m is not None: m_uas_10m_crudo[m_uas_10m_crudo == nodata_uas_10m] = np.nan
            m_uas_10m = (m_uas_10m_crudo + uas_offset) / uas_scale
            firma_uas_10m = np.nanmean(m_uas_10m, axis=0)
            for b in range(uas_10m_src.count):
                if (b + 1) in band_names_uas_map:
                    resultados.append({'Cobertura': clase_actual, 'Banda': band_names_uas_map[b + 1], 'Sensor': 'Uas (10m)', 'Reflectancia': firma_uas_10m[b]})
            datos_indices.extend(extraer_indices(m_uas_10m, uas_idx_map, 'Uas (10m)', clase_actual))

        if sat_src:
            m_sat_crudo = np.array(list(sat_src.sample(coordenadas))).astype(float)
            if nodata_sat is not None: m_sat_crudo[m_sat_crudo == nodata_sat] = np.nan
            m_sat = (m_sat_crudo + sat_offset) / sat_scale

            if uas_10m_src and data_dict['tipo_datos'] == "Multiespectral (dron/satélite)":
                mask_ambos = ~np.isnan(m_uas_10m).any(axis=1) & ~np.isnan(m_sat).any(axis=1)
                m_uas_filt, m_sat_filt = m_uas_10m[mask_ambos], m_sat[mask_ambos]
                firma_sat = np.nanmean(m_sat_filt, axis=0) if len(m_sat_filt) > 0 else np.nanmean(m_sat, axis=0)
            else:
                firma_sat = np.nanmean(m_sat, axis=0)

            for b in range(sat_src.count):
                if data_dict['tipo_datos'] == "Multiespectral (dron/satélite)":
                    if (b + 1) in band_names_sat_map:
                        resultados.append({'Cobertura': clase_actual, 'Banda': band_names_sat_map[b + 1], 'Sensor': sat_name, 'Reflectancia': firma_sat[b]})
                else:
                    banda_nombre = band_names_sat_map.get(b + 1, f"Banda_{b+1}")
                    val = firma_sat[b]
                    if not np.isnan(val) and val != 0:
                        resultados.append({'Cobertura': clase_actual, 'Banda': banda_nombre, 'Sensor': sat_name, 'Reflectancia': val, 'idx_real': b})

            if data_dict['tipo_datos'] == "Multiespectral (dron/satélite)":
                datos_indices.extend(extraer_indices(m_sat, sat_idx_map, sat_name, clase_actual))

            if m_uas_filt is not None and m_sat_filt is not None and data_dict['tipo_datos'] == "Multiespectral (dron/satélite)":
                for nb in bandas_comunes:
                    u_idx = {n: i for i, n in [(b_idx, "Azul"), (g_idx, "Verde"), (r_idx, "Rojo"), (re_idx, "Red edge"), (n_idx, "Nir"), (swir1_idx, "Swir 1"), (swir2_idx, "Swir 2")] if i > 0}[nb] - 1
                    s_idx = {n: i for i, n in [(s_b_idx, "Azul"), (s_g_idx, "Verde"), (s_r_idx, "Rojo"), (s_re_idx, "Red edge"), (s_n_idx, "Nir"), (s_swir1_idx, "Swir 1"), (s_swir2_idx, "Swir 2")] if i > 0}[nb] - 1
                    if u_idx < m_uas_filt.shape[1] and s_idx < m_sat_filt.shape[1]:
                        for uv, sv in zip(m_uas_filt[:, u_idx], m_sat_filt[:, s_idx]):
                            datos_correlacion.append({'Cobertura': clase_actual, 'Banda': nb, 'Uas': uv, 'Sat': sv})
                
                idx_u_dict = calc_idx_array(m_uas_filt, uas_idx_map)
                idx_s_dict = calc_idx_array(m_sat_filt, sat_idx_map)
                for idx_name in idx_u_dict.keys():
                    if idx_name in idx_s_dict:
                        for uv, sv in zip(idx_u_dict[idx_name], idx_s_dict[idx_name]):
                            if not np.isnan(uv) and not np.isnan(sv):
                                datos_corr_idx.append({'Cobertura': clase_actual, 'Índice': idx_name, 'Uas': uv, 'Sat': sv})

    if uas_10m_src: uas_10m_src.close()
    if uas_raw_src: uas_raw_src.close()
    if sat_src: sat_src.close()
    return pd.DataFrame(resultados), pd.DataFrame(datos_correlacion), pd.DataFrame(datos_indices), pd.DataFrame(datos_corr_idx)

def generar_mapa_crudo(data_dict, sensor_sel, vis_mode, bandas_config, sat_scale, sat_offset, uas_scale, uas_offset, escena_name, banda_sel=1):
    is_sat = (sensor_sel == "Satélite")
    base_path = data_dict['uas_path_1m'] if data_dict['has_uas'] else data_dict['sat_clip_path']

    b_idx, g_idx, r_idx, re_idx, n_idx, swir1_idx, swir2_idx = (0,0,0,0,0,0,0)
    s_b_idx, s_g_idx, s_r_idx, s_re_idx, s_n_idx, s_swir1_idx, s_swir2_idx = (0,0,0,0,0,0,0)

    if data_dict['tipo_datos'] == "Multiespectral (dron/satélite)":
        b_idx, g_idx, r_idx, re_idx, n_idx, swir1_idx, swir2_idx = bandas_config['uas']
        s_b_idx, s_g_idx, s_r_idx, s_re_idx, s_n_idx, s_swir1_idx, s_swir2_idx = bandas_config['sat']

    with rasterio.open(base_path) as base_src:
        ext = [base_src.bounds.left, base_src.bounds.right, base_src.bounds.bottom, base_src.bounds.top]
        base_data = base_src.read()
        master_mask = (base_data <= 0).all(axis=0) if data_dict['has_uas'] else (base_data == 0).all(axis=0)

        def obt_banda(idx_u, idx_s):
            out = np.full((base_src.height, base_src.width), np.nan, dtype=np.float32)
            if not is_sat and data_dict['has_uas']:
                if 0 < idx_u <= base_src.count:
                    out = base_src.read(int(idx_u)).astype(float)
                    no_data_mask = (out <= 0)
                    out = (out + uas_offset) / uas_scale
                    out[no_data_mask] = np.nan
            elif is_sat and data_dict['has_sat']:
                with rasterio.open(data_dict['sat_clip_path']) as ss:
                    if 0 < idx_s <= ss.count:
                        reproject(rasterio.band(ss, int(idx_s)), out, src_transform=ss.transform, src_crs=ss.crs, dst_transform=base_src.transform, dst_crs=base_src.crs, resampling=Resampling.bilinear)
                        no_data_mask = (out <= 0)
                        out = (out + sat_offset) / sat_scale
                        out[no_data_mask] = np.nan
            out[master_mask] = np.nan
            return out

        def norm_perc(arr):
            if np.isnan(arr).all(): return 0, 1
            return np.nanpercentile(arr, [2, 98])

        def check_missing(*bands): return any(np.isnan(b).all() for b in bands)

        fig = plt.figure(figsize=(12, 5.5), dpi=150)
        gs = fig.add_gridspec(1, 3, width_ratios=[3, 1, 1])
        ax, axr, axn = fig.add_subplot(gs[0]), fig.add_subplot(gs[1]), fig.add_subplot(gs[2])

        def plot_missing(msg):
            ax.text(0.5, 0.5, f'Banda(s) faltante(s)\npara {msg}', ha='center', va='center', transform=ax.transAxes, color='red', fontsize=12, weight='bold', bbox=dict(facecolor='white', alpha=0.8, edgecolor='red'))
            ax.imshow(np.zeros((10, 10)), cmap='gray', extent=ext, vmin=0, vmax=1)

        if vis_mode == "Ndvi":
            rn, rr = obt_banda(n_idx, s_n_idx), obt_banda(r_idx, s_r_idx)
            if check_missing(rn, rr): plot_missing("NDVI")
            else:
                ndvi = (rn - rr) / (rn + rr + 1e-6); p2, p98 = norm_perc(ndvi)
                im = ax.imshow(ndvi, cmap='RdYlGn', vmin=p2, vmax=p98, extent=ext, interpolation='bicubic')
                fig.colorbar(im, ax=ax, shrink=0.7, pad=0.02).set_label('Ndvi')

        elif vis_mode == "Ndwi":
            rg, rn = obt_banda(g_idx, s_g_idx), obt_banda(n_idx, s_n_idx)
            if check_missing(rg, rn): plot_missing("NDWI")
            else:
                ndwi = (rg - rn) / (rg + rn + 1e-6); p2, p98 = norm_perc(ndwi)
                im = ax.imshow(ndwi, cmap='GnBu', vmin=p2, vmax=p98, extent=ext, interpolation='bicubic')
                fig.colorbar(im, ax=ax, shrink=0.7, pad=0.02).set_label('Ndwi')

        elif vis_mode == "Mndwi":
            u_swir_use = swir1_idx if swir1_idx > 0 else swir2_idx
            s_swir_use = s_swir1_idx if s_swir1_idx > 0 else s_swir2_idx
            rg, rsw = obt_banda(g_idx, s_g_idx), obt_banda(u_swir_use, s_swir_use)
            if check_missing(rg, rsw): plot_missing("MNDWI")
            else:
                mndwi = (rg - rsw) / (rg + rsw + 1e-6); p2, p98 = norm_perc(mndwi)
                im = ax.imshow(mndwi, cmap='Blues', vmin=p2, vmax=p98, extent=ext, interpolation='bicubic')
                fig.colorbar(im, ax=ax, shrink=0.7, pad=0.02).set_label('Mndwi')

        elif vis_mode == "Ndmi":
            u_swir_use = swir1_idx if swir1_idx > 0 else swir2_idx
            s_swir_use = s_swir1_idx if s_swir1_idx > 0 else s_swir2_idx
            rn, rsw = obt_banda(n_idx, s_n_idx), obt_banda(u_swir_use, s_swir_use)
            if check_missing(rn, rsw): plot_missing("NDMI")
            else:
                ndmi = (rn - rsw) / (rn + rsw + 1e-6); p2, p98 = norm_perc(ndmi)
                im = ax.imshow(ndmi, cmap='BrBG', vmin=p2, vmax=p98, extent=ext, interpolation='bicubic')
                fig.colorbar(im, ax=ax, shrink=0.7, pad=0.02).set_label('Ndmi')

        elif vis_mode == "Savi":
            rn, rr = obt_banda(n_idx, s_n_idx), obt_banda(r_idx, s_r_idx)
            if check_missing(rn, rr): plot_missing("SAVI")
            else:
                savi = ((rn - rr) / (rn + rr + 0.5)) * 1.5; p2, p98 = norm_perc(savi)
                im = ax.imshow(savi, cmap='RdYlGn', vmin=p2, vmax=p98, extent=ext, interpolation='bicubic')
                fig.colorbar(im, ax=ax, shrink=0.7, pad=0.02).set_label('Savi')

        elif "color" in vis_mode.lower() or "rgb" in vis_mode.lower():
            is_falso = "falso" in vis_mode.lower()
            b1_u, b1_s = (n_idx, s_n_idx) if is_falso else (r_idx, s_r_idx)
            b2_u, b2_s = (r_idx, s_r_idx) if is_falso else (g_idx, s_g_idx)
            b3_u, b3_s = (g_idx, s_g_idx) if is_falso else (b_idx, s_b_idx)

            c1 = obt_banda(b1_u, b1_s)
            c2 = obt_banda(b2_u, b2_s)
            c3 = obt_banda(b3_u, b3_s)

            if check_missing(c1, c2, c3): plot_missing(vis_mode)
            else:
                c1_n, c2_n, c3_n = norm_perc(c1), norm_perc(c2), norm_perc(c3)
                def aplicar_norm(arr, min_v, max_v): return (np.clip(arr, min_v, max_v) - min_v) / (max_v - min_v + 1e-6)
                c1_f = aplicar_norm(c1, c1_n[0], c1_n[1])
                c2_f = aplicar_norm(c2, c2_n[0], c2_n[1])
                c3_f = aplicar_norm(c3, c3_n[0], c3_n[1])
                ax.imshow(np.dstack([np.nan_to_num(c1_f, nan=1.0), np.nan_to_num(c2_f, nan=1.0), np.nan_to_num(c3_f, nan=1.0), np.where(np.isnan(c1_f), 0, 1)]), extent=ext, interpolation='bicubic')

        elif "banda individual" in vis_mode.lower():
            b_norm = obt_banda(banda_sel, banda_sel)
            if check_missing(b_norm): plot_missing(f"Banda {banda_sel}")
            else:
                p2, p98 = norm_perc(b_norm)
                b_f = (np.clip(b_norm, p2, p98) - p2) / (p98 - p2 + 1e-6)
                ax.imshow(b_f, cmap='gray', extent=ext, interpolation='bicubic')

        create_context_maps(axr, axn, data_dict.get('gdf'), ext, base_src.crs)
        add_cartographic_elements(ax, True, f"{vis_mode} - {escena_name}")
        fig.subplots_adjust(left=0.02, right=0.98, wspace=0.1)
        buf = io.BytesIO(); fig.savefig(buf, format="png", bbox_inches='tight', facecolor='white'); plt.close(fig)
        return buf.getvalue()

def generar_todos_pre_mapas(data_dict, sat_scale, sat_offset, uas_scale, uas_offset, bandas_config, escena_name):
    pre_mapas = {}
    modos_pre = ["Rgb (color real)", "Falso color (nir-r-g)", "Ndvi", "Ndwi", "Mndwi", "Ndmi", "Savi"]
    sensores_pre = []
    if data_dict['has_uas'] and data_dict['tipo_datos'] == "Multiespectral (dron/satélite)": sensores_pre.append("Uas")
    if data_dict['has_sat'] and data_dict['tipo_datos'] == "Multiespectral (dron/satélite)": sensores_pre.append("Satélite")
    for sensor in sensores_pre:
        for modo in modos_pre:
            pre_mapas[f"{sensor}_{modo}"] = generar_mapa_crudo(data_dict, sensor, modo, bandas_config, sat_scale, sat_offset, uas_scale, uas_offset, escena_name)
    return pre_mapas

def pre_generar_graficos(df_firmas, sat_name, tipo_datos, color_map, escena_name):
    pre_firmas = {}
    pre_firmas_plt = {}
    buf_gen_uas = None; buf_gen_sat = None; buf_gen_hs = None
    fig_gen_uas = None; fig_gen_sat = None; fig_gen_hs = None
    
    if df_firmas.empty: return pre_firmas, pre_firmas_plt, fig_gen_uas, buf_gen_uas, fig_gen_sat, buf_gen_sat, fig_gen_hs, buf_gen_hs

    df_limpio = df_firmas[df_firmas['Reflectancia'] > 0]
    coberturas = df_limpio['Cobertura'].unique()
    sensores_validos = ['Uas (10m)', sat_name, 'Uas (nativo)'] if tipo_datos == "Multiespectral (dron/satélite)" else [sat_name]
    df_comparacion = df_limpio[df_limpio['Sensor'].isin(sensores_validos)]

    y_min = df_limpio['Reflectancia'].min()
    y_max = df_limpio['Reflectancia'].max()
    y_padding = (y_max - y_min) * 0.05
    y_range = [max(0, y_min - y_padding), y_max + y_padding]

    if tipo_datos == "Multiespectral (dron/satélite)":
        df_uas_nat = df_limpio[df_limpio['Sensor'] == 'Uas (nativo)'].copy()
        if not df_uas_nat.empty:
            fig_gen_uas = px.line(df_uas_nat, x="Banda", y="Reflectancia", color="Cobertura", color_discrete_map=color_map, markers=True, title="Resolución nativa Dron (UAS)")
            fig_gen_uas.update_xaxes(categoryorder='array', categoryarray=["Azul", "Verde", "Rojo", "Red edge", "Nir", "Swir 1", "Swir 2"], showgrid=True, gridcolor='LightGray')
            fig_gen_uas.update_traces(line=dict(width=2), marker=dict(size=8))
            fig_gen_uas.update_layout(template="simple_white", height=550, plot_bgcolor='white', legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None))
            fig_gen_uas.update_yaxes(range=y_range, showgrid=True, gridcolor='LightGray')
            buf_gen_uas = export_formal_general(df_uas_nat, f'Dron UAS - {escena_name}', tipo_datos, color_map, y_range[0], y_range[1])

        df_sat = df_limpio[df_limpio['Sensor'] == sat_name].copy()
        if not df_sat.empty:
            fig_gen_sat = px.line(df_sat, x="Banda", y="Reflectancia", color="Cobertura", color_discrete_map=color_map, markers=True, title=f"Resolución Satélite: {sat_name}")
            fig_gen_sat.update_xaxes(categoryorder='array', categoryarray=["Azul", "Verde", "Rojo", "Red edge", "Nir", "Swir 1", "Swir 2"], showgrid=True, gridcolor='LightGray')
            fig_gen_sat.update_traces(marker=dict(size=8), line=dict(width=2))
            fig_gen_sat.update_layout(template="simple_white", height=550, plot_bgcolor='white', legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None))
            fig_gen_sat.update_yaxes(range=y_range, showgrid=True, gridcolor='LightGray')
            buf_gen_sat = export_formal_general(df_sat, f'{sat_name} - {escena_name}', tipo_datos, color_map, y_range[0], y_range[1])
    else:
        df_sat = df_limpio[df_limpio['Sensor'] == sat_name].copy()
        if not df_sat.empty:
            df_sat['Wavelength'] = df_sat['Banda'].astype(str).str.extract(r'(\d+)').astype(float)
            x_col = "Wavelength" if not df_sat['Wavelength'].isnull().all() else "idx_real"
            df_sat = df_sat.sort_values(x_col)
            fig_gen_hs = px.line(df_sat, x=x_col, y="Reflectancia", color="Cobertura", color_discrete_map=color_map, markers=False, title=f"Resolución hiperespectral {sat_name}")
            fig_gen_hs.update_xaxes(showgrid=True, gridcolor='LightGray', title="Longitud de onda (nm)" if x_col == "Wavelength" else "Banda")
            fig_gen_hs.update_traces(line=dict(width=2))
            fig_gen_hs.update_layout(template="simple_white", height=600, plot_bgcolor='white', legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None))
            fig_gen_hs.update_yaxes(range=y_range, showgrid=True, gridcolor='LightGray')
            add_spectral_bands_plotly(fig_gen_hs)
            buf_gen_hs = export_formal_general(df_sat, f'{sat_name} - {escena_name}', tipo_datos, color_map, y_range[0], y_range[1])

    for cob in coberturas:
        df_f = df_comparacion[df_comparacion['Cobertura'] == cob].copy()
        if tipo_datos == "Multiespectral (dron/satélite)":
             orden_bandas = ["Azul", "Verde", "Rojo", "Red edge", "Nir", "Swir 1", "Swir 2"]
             fig_f = px.line(df_f, x="Banda", y="Reflectancia", color="Sensor", markers=True, 
                             title=f"Firma comparativa: {cob}", color_discrete_map={'Uas (10m)':'#1f77b4', 'Uas (nativo)':'#2ca02c', sat_name:'#8c564b'})
             fig_f.update_xaxes(categoryorder='array', categoryarray=orden_bandas, showgrid=True, gridcolor='LightGray')
             fig_f.update_traces(line=dict(width=2), marker=dict(size=8, symbol='circle'))
        else: 
             df_f['Wavelength'] = df_f['Banda'].astype(str).str.extract(r'(\d+)').astype(float)
             x_col = "Wavelength" if not df_f['Wavelength'].isnull().all() else "idx_real"
             df_f = df_f.sort_values(x_col)
             fig_f = px.line(df_f, x=x_col, y="Reflectancia", color="Sensor", markers=False, 
                             title=f"Firma hiperespectral: {cob}", color_discrete_sequence=[color_map.get(cob, '#8c564b')])
             fig_f.update_traces(line=dict(width=2))
             fig_f.update_xaxes(showgrid=True, gridcolor='LightGray', title="Longitud de onda (nm)" if x_col == "Wavelength" else "Banda")
             add_spectral_bands_plotly(fig_f)

        fig_f.update_yaxes(range=y_range, showgrid=True, gridcolor='LightGray', title="Reflectancia") 
        fig_f.update_layout(template="simple_white", plot_bgcolor='white', legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None), margin=dict(l=10, r=10, t=40, b=80))
        pre_firmas[cob] = fig_f
        pre_firmas_plt[cob] = export_formal_signature(df_f, cob, sat_name, tipo_datos, color_map, y_range[0], y_range[1], f"({escena_name})")
        
    return pre_firmas, pre_firmas_plt, fig_gen_uas, buf_gen_uas, fig_gen_sat, buf_gen_sat, fig_gen_hs, buf_gen_hs

def pre_generar_graficos_globales(all_f, all_c_filt, sat_name_sesion, tipo_datos_sesion, color_map):
    res = {}
    cobs = all_f['Cobertura'].unique()
    names = all_f['Escena'].unique()

    y_min_g = all_f['Reflectancia'].min()
    y_max_g = all_f['Reflectancia'].max()
    y_padding_g = (y_max_g - y_min_g) * 0.05
    y_range_g = [max(0, y_min_g - y_padding_g), y_max_g + y_padding_g]

    if tipo_datos_sesion == "Multiespectral (dron/satélite)":
        for c in cobs:
            df_c_uas = all_f[(all_f['Cobertura'] == c) & (all_f['Sensor'] == 'Uas (nativo)')]
            if not df_c_uas.empty:
                res[f'buf_glob_uas_{c}'] = export_formal_signature(df_c_uas, c, sat_name_sesion, tipo_datos_sesion, color_map, y_range_g[0], y_range_g[1], "(Evolución UAS)")
            
            df_c_sat = all_f[(all_f['Cobertura'] == c) & (all_f['Sensor'] == sat_name_sesion)]
            if not df_c_sat.empty:
                res[f'buf_glob_sat_{c}'] = export_formal_signature(df_c_sat, c, sat_name_sesion, tipo_datos_sesion, color_map, y_range_g[0], y_range_g[1], f"(Evolución {sat_name_sesion})")
    else:
        for c in cobs:
            df_c_hs = all_f[(all_f['Cobertura'] == c) & (all_f['Sensor'] == sat_name_sesion)]
            if not df_c_hs.empty:
                res[f'buf_glob_hs_{c}'] = export_formal_signature(df_c_hs, c, sat_name_sesion, tipo_datos_sesion, color_map, y_range_g[0], y_range_g[1], f"(Evolución {sat_name_sesion})")

    if all_c_filt is not None and not all_c_filt.empty:
        r2_list = []
        for n in names:
            df_esc = all_c_filt[all_c_filt['Escena'] == n]
            for c in cobs:
                df_sub = df_esc[df_esc['Cobertura'] == c]
                if len(df_sub) > 2:
                    mod, r2_val = calcular_regresion_limpia(df_sub)
                    r2_list.append({'Escena': n, 'Cobertura': c, 'R2': r2_val})
        
        if r2_list:
            df_r2_glob = pd.DataFrame(r2_list)
            fig, ax = plt.subplots(figsize=(8, 5), dpi=300)
            df_pivot = df_r2_glob.pivot(index='Cobertura', columns='Escena', values='R2')
            df_pivot.plot(kind='bar', ax=ax, cmap='PuBuGn')
            mean_r2 = df_r2_glob['R2'].mean()
            ax.axhline(y=mean_r2, color='red', linestyle='--', label=f'Promedio global ({mean_r2:.3f})')
            ax.set_title("Comparación R² por cobertura y escena", weight='bold')
            ax.set_ylabel("R²")
            ax.legend(frameon=True, facecolor='white', edgecolor='black')
            plt.tight_layout()
            buf = io.BytesIO(); fig.savefig(buf, format="png", bbox_inches='tight'); plt.close(fig)
            res['buf_glob_bar_r2'] = buf.getvalue()

            for c in cobs:
                df_sub = all_c_filt[all_c_filt['Cobertura'] == c]
                if len(df_sub) > 2:
                    mod_g, r2_g = calcular_regresion_limpia(df_sub)
                    res[f'buf_glob_scat_{c}'] = export_formal_scatter(df_sub, f"Regresión radiométrica global: {c}", r2_g)
    
    return res

# -----------------------------
# 3. Interfaz (sidebar)
# -----------------------------
with st.sidebar:
    st.header("Configuración del proyecto")
    tipo_datos = st.selectbox("Modalidad de análisis", ["1. Multiespectral (dron/satélite)", "2. Hiperespectral"])
    
    with st.expander("1. Archivo vectorial (opcional)", expanded=False):
        vector_file = st.file_uploader("Archivo vectorial", type=["zip", "gpkg", "GPKG"])
        if vector_file:
            preview_gdf = load_vector_preview(vector_file)
            st.session_state.raw_gdf = preview_gdf
            st.session_state.has_vector = True
            resumen_columnas = [{"Columna": c, "Ejemplos": ", ".join(map(str, preview_gdf[c].dropna().unique()[:3]))} for c in preview_gdf.columns if c != 'geometry']
            st.dataframe(pd.DataFrame(resumen_columnas), hide_index=True, width="stretch")
            st.session_state.col_clase = st.selectbox("Columna clase:", [c for c in preview_gdf.columns if c != 'geometry'], key='selector_clase')
        else:
            st.session_state.has_vector = False

    st.markdown("---")
    st.session_state.usar_cartografia = st.checkbox("Activar visor espacial", value=True)
    st.markdown("---")
            
    num_escenas = st.number_input("2. Cantidad de escenas a analizar", 1, 10, 1)
    archivos_escenas = []
    for i in range(1, num_escenas + 1):
        with st.expander(f"Archivos escena {i}", expanded=True if i == 1 else False):
            if tipo_datos == "1. Multiespectral (dron/satélite)":
                 archivos_escenas.append({"id": i, "uas": st.file_uploader(f"Uas {i} (dron)", type=["tif"]), "sat": st.file_uploader(f"Sat {i} (satélite)", type=["tif"])})
            else:
                 archivos_escenas.append({"id": i, "uas": None, "sat": st.file_uploader(f"Imagen hiperespectral {i} (tif)", type=["tif"])})
            
    st.markdown("---")
    st.markdown("**3. Ajustes radiométricos (Escalas y Offsets)**")
    
    presets_satelites = {
        "Google Earth Engine (Escala 10000)": {"escala": 10000.0, "offset": 0.0},
        "Google Earth Engine (Reflectancia 0-1)": {"escala": 1.0, "offset": 0.0},
        "Sentinel-2 (L2A post-2022)": {"escala": 10000.0, "offset": -1000.0},
        "Sentinel-2 (L2A pre-2022)": {"escala": 10000.0, "offset": 0.0},
        "Landsat 8/9 (Collection 2 Level 2)": {"escala": 36363.636, "offset": -7272.727},
        "PlanetScope (SuperDove)": {"escala": 10000.0, "offset": 0.0},
        "Personalizado": {"escala": 10000.0, "offset": 0.0}
    }
    
    if "Hiperespectral" in tipo_datos:
         presets_satelites["Prisma (L2D)"] = {"escala": 65535.0, "offset": 0.0}
    
    st.markdown("*Satélite*")
    sat_preset = st.selectbox("Seleccionar sensor satelital:", list(presets_satelites.keys()), index=list(presets_satelites.keys()).index("Prisma (L2D)") if "Hiperespectral" in tipo_datos else 0)
    st.caption("Nota: GEE usa Escala 10000. Si tu imagen es Sentinel-2 desde Copérnico (2022 en adelante), usa el preset post-2022 (offset -1000).")
    
    sat_name = st.text_input("Nombre en gráficos:", sat_preset.split(" (")[0] if sat_preset not in ["Personalizado", "Google Earth Engine (Reflectancia 0-1)", "Google Earth Engine (Escala 10000)"] else "Satélite GEE")
    es_personalizado = (sat_preset == "Personalizado")
    
    c_s1, c_s2 = st.columns(2)
    with c_s1: sat_scale = st.number_input("Escala Satélite", value=presets_satelites[sat_preset]["escala"], format="%.3f", disabled=not es_personalizado)
    with c_s2: sat_offset = st.number_input("Offset Satélite", value=presets_satelites[sat_preset]["offset"], format="%.3f", disabled=not es_personalizado)

    st.markdown("*Dron (UAS)*")
    c_u1, c_u2 = st.columns(2)
    with c_u1: uas_scale = st.number_input("Escala Dron", value=1.0, format="%.3f")
    with c_u2: uas_offset = st.number_input("Offset Dron", value=0.0, format="%.3f")
    
    st.markdown("---")
    bandas_config = {'uas': [], 'sat': [], 'sat_names': {}, 'uas_nm': []}
    
    if tipo_datos == "1. Multiespectral (dron/satélite)":
        st.markdown("**4. Configuración de bandas (índice)**")
        st.caption("Si una banda no existe, ingrese 0.")
        c1, c2 = st.columns(2)
        with c1: 
            st.markdown("**Uas (dron)**")
            u_b = st.number_input("U-b", min_value=0, value=1, step=1)
            u_g = st.number_input("U-g", min_value=0, value=2, step=1)
            u_r = st.number_input("U-r", min_value=0, value=3, step=1)
            u_re = st.number_input("U-re", min_value=0, value=4, step=1)
            u_n = st.number_input("U-n", min_value=0, value=5, step=1)
            u_swir1 = st.number_input("U-swir 1", min_value=0, value=0, step=1)
            u_swir2 = st.number_input("U-swir 2", min_value=0, value=0, step=1)
            bandas_config['uas'] = [u_b, u_g, u_r, u_re, u_n, u_swir1, u_swir2]
        with c2: 
            st.markdown("**Satélite**")
            s_b = st.number_input("S-b", min_value=0, value=1, step=1)
            s_g = st.number_input("S-g", min_value=0, value=2, step=1)
            s_r = st.number_input("S-r", min_value=0, value=3, step=1)
            s_re = st.number_input("S-re", min_value=0, value=4, step=1)
            s_n = st.number_input("S-n", min_value=0, value=5, step=1)
            s_swir1 = st.number_input("S-swir 1", min_value=0, value=6, step=1)
            s_swir2 = st.number_input("S-swir 2", min_value=0, value=7, step=1)
            bandas_config['sat'] = [s_b, s_g, s_r, s_re, s_n, s_swir1, s_swir2]
    else:
        st.info("Para datos hiperespectrales puros, la plataforma leerá las bandas automáticamente. El visor espacial operará en modo exploración (banda a banda).")

    if st.button("Ejecutar plataforma", type="primary", use_container_width=True):
        if archivos_escenas[0]['uas'] is None and archivos_escenas[0]['sat'] is None:
            st.error("Se requiere al menos una imagen en la primera escena para iniciar el entorno.")
        else:
            with st.spinner("Inicializando motor espacial..."):
                try:
                    archivo_maestro = archivos_escenas[0]['uas'] if archivos_escenas[0]['uas'] is not None else archivos_escenas[0]['sat']
                    with MemoryFile(archivo_maestro.getvalue()) as mem: 
                        master_crs = mem.open().crs
                    if master_crs.is_geographic:
                        st.error("Error de coordenadas: el archivo principal utiliza grados geográficos. Se requiere un sistema proyectado métrico (ejemplo: utm).")
                    else:
                        raw_gdf = st.session_state.raw_gdf.to_crs(master_crs) if st.session_state.get('has_vector') else None
                        st.session_state.master_gdf = raw_gdf
                        st.session_state.data_escenas = {}
                        st.session_state.bandas_config = bandas_config
                        
                        tipo_simplificado = "Multiespectral (dron/satélite)" if tipo_datos == "1. Multiespectral (dron/satélite)" else "Hiperespectral"
                        st.session_state.tipo_datos = tipo_simplificado
                        st.session_state.sat_name = sat_name
                        
                        for e in archivos_escenas:
                            if e['uas'] is not None or e['sat'] is not None:
                                name = parse_scene_name(e['uas'].name if e['uas'] else e['sat'].name)
                                db = inicializar_base(e['uas'], e['sat'], master_crs, raw_gdf, st.session_state.get('col_clase'), tipo_simplificado)
                                st.session_state.data_escenas[name] = db
                                
                        st.session_state.analisis_listo = True
                        if st.session_state.get('has_vector'): st.success("Modo completo activado: visualización y análisis estadístico.")
                        else: st.info("Modo visor activado: solo visualización espacial (sin extracción de datos).")
                except ValueError as err: st.error(f"Falla en el procesamiento de límites espaciales: {err}")
                except Exception as err: st.error(f"Error interno durante la inicialización: {err}")
                
    if st.button("Reiniciar entorno", use_container_width=True): st.session_state.clear(); st.rerun()

# -----------------------------
# 5. Renderizado progresivo
# -----------------------------
if st.session_state.get("analisis_listo"):
    has_vector = st.session_state.get('has_vector', False)
    col_clase_input = st.session_state.get('col_clase', None)
    names = list(st.session_state.data_escenas.keys())
    tipo_datos_sesion = st.session_state.get('tipo_datos', "Multiespectral (dron/satélite)")
    sat_name_sesion = st.session_state.get('sat_name', "Satélite")
    
    tab_titles = [f"Resultados {n}" for n in names]
    if has_vector and len(names) > 0: tab_titles.append("Comparación global")
    tabs = st.tabs(tab_titles)
    
    if has_vector and 'color_map' not in st.session_state:
        unique_classes = st.session_state.master_gdf[col_clase_input].unique()
        palette = px.colors.qualitative.Plotly * 10 
        st.session_state.color_map = {c: palette[i] for i, c in enumerate(unique_classes)}

    for idx, name in enumerate(names):
        with tabs[idx]:
            d = st.session_state.data_escenas[name]
            st.header(f"Escena: {name}")
            
            # BLOQUE DE CARGA CACHEADA PERSISTENTE
            if 'df_firmas' not in d and has_vector and d.get('gdf') is not None:
                loading_ph = st.empty()
                with loading_ph.container():
                    st.markdown("<h3 style='text-align: center;'>Procesando escena espacial...</h3>", unsafe_allow_html=True)
                    status_text, pbar = st.empty(), st.progress(0)
                    
                    status_text.info("Procesamiento: muestreo radiométrico estocástico iniciado...")
                    df_f, df_c, df_i, df_corr_idx = calcular_firmas(d, col_clase_input, sat_scale, sat_offset, uas_scale, uas_offset, st.session_state.bandas_config, sat_name_sesion)
                    d['df_firmas'], d['df_corr'], d['df_indices'], d['df_corr_idx'] = df_f, df_c, df_i, df_corr_idx
                    pbar.progress(33)
                    
                    status_text.info("Procesamiento: modelado de firmas espectrales y reportes...")
                    d['pre_p_f'], d['pre_p_plt'], d['fig_gen_uas'], d['buf_gen_uas'], d['fig_gen_sat'], d['buf_gen_sat'], d['fig_gen_hs'], d['buf_gen_hs'] = pre_generar_graficos(df_f, sat_name_sesion, tipo_datos_sesion, st.session_state.color_map, name)
                    pbar.progress(66)
                    
                    if st.session_state.usar_cartografia and tipo_datos_sesion == "Multiespectral (dron/satélite)":
                        status_text.info("Procesamiento: renderización espacial...")
                        d['pre_m'] = generar_todos_pre_mapas(d, sat_scale, sat_offset, uas_scale, uas_offset, st.session_state.bandas_config, name)
                    
                    d['idx_buffers'] = {}
                    d['idx_scat_buffers'] = {}
                    if not df_i.empty:
                        for idx_sel in df_i['Índice'].unique():
                            df_ind_filt = df_i[df_i['Índice'] == idx_sel]
                            d['idx_buffers'][idx_sel] = export_formal_boxplot(df_ind_filt, idx_sel, sat_name_sesion)
                            if df_corr_idx is not None and not df_corr_idx.empty:
                                df_c_idx_filt = df_corr_idx[df_corr_idx['Índice'] == idx_sel]
                                if not df_c_idx_filt.empty and len(df_c_idx_filt) > 2:
                                    _, r2_idx = calcular_regresion_limpia(df_c_idx_filt)
                                    d['idx_scat_buffers'][idx_sel] = export_formal_scatter(df_c_idx_filt, f"Relación {idx_sel}: {name}", r2_idx, es_indice=True)
                    
                    d['reg_buffers'] = {}
                    if not df_c.empty:
                        for c in df_c['Cobertura'].unique():
                            df_sub = df_c[df_c['Cobertura'] == c]
                            if len(df_sub) > 2:
                                _, r2_g = calcular_regresion_limpia(df_sub)
                                d['reg_buffers'][c] = export_formal_scatter(df_sub, f"Regresión radiométrica: {c} ({name})", r2_g)
                                
                    pbar.progress(100)
                st.session_state.data_escenas[name] = d; loading_ph.empty()
            elif 'pre_m' not in d and st.session_state.usar_cartografia and tipo_datos_sesion == "Multiespectral (dron/satélite)":
                loading_ph = st.empty()
                with loading_ph.container():
                    st.info("Procesamiento: renderización espacial..."); pbar = st.progress(50)
                    d['pre_m'] = generar_todos_pre_mapas(d, sat_scale, sat_offset, uas_scale, uas_offset, st.session_state.bandas_config, name); pbar.progress(100)
                st.session_state.data_escenas[name] = d; loading_ph.empty()

            sub_tabs_names = []
            if st.session_state.usar_cartografia: sub_tabs_names.append("Visor espacial")
            if has_vector:
                if tipo_datos_sesion == "Multiespectral (dron/satélite)": sub_tabs_names.extend(["Firmas espectrales", "Estadística de índices", "Ajuste radiométrico"])
                else: sub_tabs_names.append("Análisis de firmas hiperespectrales")
            
            if not sub_tabs_names: continue
            sub_tabs = st.tabs(sub_tabs_names)
            tab_idx = 0
            
            if st.session_state.usar_cartografia:
                with sub_tabs[tab_idx]:
                    if d.get('has_uas') or d.get('has_sat'):
                        col_mapa, col_torta = st.columns([2, 1])
                        with col_mapa:
                            caja_wgs84 = d['caja_interseccion_wgs84']
                            centro_y = caja_wgs84.geometry.iloc[0].centroid.y
                            centro_x = caja_wgs84.geometry.iloc[0].centroid.x
                            m = folium.Map(location=[centro_y, centro_x], zoom_start=14)
                            folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google', name='Google Satellite').add_to(m)
                            
                            if d.get('bounds_sat_orig') is not None: folium.GeoJson(d['bounds_sat_orig'], style_function=lambda x: {'fillColor': 'none', 'color': '#d62728', 'weight': 2, 'dashArray': '5, 5'}, name='Límite Satélite').add_to(m)
                            if d.get('bounds_uas_orig') is not None: folium.GeoJson(d['bounds_uas_orig'], style_function=lambda x: {'fillColor': 'none', 'color': '#1f77b4', 'weight': 2, 'dashArray': '5, 5'}, name='Límite Dron (UAS)').add_to(m)

                            if has_vector and d.get('gdf') is not None and not d['gdf'].empty:
                                gdf_map = d['gdf'].to_crs(epsg=4326)
                                gdf_map["color"] = gdf_map[col_clase_input].map(st.session_state.color_map).fillna("#cccccc")
                                folium.GeoJson(gdf_map, style_function=lambda f: {'fillColor': f['properties']['color'], 'color': 'white', 'weight': 1, 'fillOpacity': 0.7}, tooltip=folium.GeoJsonTooltip(fields=[col_clase_input], aliases=['Cobertura:'], style="font-weight: bold; background-color: white;"), name='Coberturas Vectoriales').add_to(m)
                            else:
                                folium.GeoJson(caja_wgs84, style_function=lambda x: {'fillColor': 'none', 'color': '#2ca02c', 'weight': 3}, name='Área de intersección').add_to(m)

                            folium.LayerControl().add_to(m)
                            st_folium(m, width=800, height=400, returned_objects=[], key=f"folium_{name}")

                        with col_torta:
                            if has_vector and d.get('gdf') is not None and not d['gdf'].empty:
                                df_stats = d['gdf_diss'].copy()
                                st.metric("Total hectáreas", f"{df_stats['area_m2'].sum()/10000:.2f} ha")
                                df_stats['label_text'] = df_stats.apply(lambda row: f"{row['area_m2']/10000:.2f} ha<br>{row['area_m2']:,.1f} m²", axis=1)
                                fig_pie = px.pie(df_stats, values='area_m2', names=col_clase_input, hole=0.4, color=col_clase_input, color_discrete_map=st.session_state.color_map, custom_data=['label_text'])
                                fig_pie.update_traces(hovertemplate="<b>%{label}</b><br>%{customdata[0]}")
                                st.plotly_chart(fig_pie, width="stretch", key=f"pie_{name}")
                            else:
                                st.info("El análisis estadístico se encuentra deshabilitado por ausencia de archivo vectorial.")
                        st.markdown("---")
                        
                    if tipo_datos_sesion == "Multiespectral (dron/satélite)":
                        s_sel_names = []
                        if d['has_uas']: s_sel_names.append("Uas")
                        if d['has_sat']: s_sel_names.append("Satélite")
                        s_sel = st.tabs(s_sel_names)
                        for i, sensor in enumerate(s_sel_names):
                            with s_sel[i]:
                                m_tabs = st.tabs(["Rgb", "Falso color", "Ndvi", "Ndwi", "Mndwi", "Ndmi", "Savi", "Banda individual"])
                                modos_cartografia = ["Rgb (color real)", "Falso color (nir-r-g)", "Ndvi", "Ndwi", "Mndwi", "Ndmi", "Savi"]
                                for j, m in enumerate(modos_cartografia):
                                    with m_tabs[j]: 
                                        st.image(d['pre_m'][f"{sensor}_{m}"], width="stretch")
                                        custom_download_button(d['pre_m'][f"{sensor}_{m}"], f"Mapa_{m}_{sensor}_{name}.png")
                                        
                                with m_tabs[7]:
                                    banda_sel = st.selectbox("Seleccione banda:", range(1, 8), key=f"bp_{name}_{sensor}")
                                    mapa_puro = generar_mapa_crudo(d, sensor, "Banda individual", st.session_state.bandas_config, sat_scale, sat_offset, uas_scale, uas_offset, name, banda_sel)
                                    st.image(mapa_puro, width="stretch")
                                    custom_download_button(mapa_puro, f"Mapa_Banda_{banda_sel}_{sensor}_{name}.png")
                    else:
                        st.markdown("### Explorador de bandas hiperespectrales")
                        if d['has_sat']:
                            with rasterio.open(d['sat_clip_path']) as src_h: max_b = src_h.count
                            banda_sel = st.slider("Deslice para barrer el espectro (n° de banda)", 1, max_b, 1, key=f"slider_h_{name}")
                            mapa_puro = generar_mapa_crudo(d, "Satélite", "Banda individual", st.session_state.bandas_config, sat_scale, sat_offset, uas_scale, uas_offset, name, banda_sel)
                            st.image(mapa_puro, width="stretch")
                            custom_download_button(mapa_puro, f"Mapa_Banda_{banda_sel}_Hiperespectral_{name}.png")
                tab_idx += 1
            
            if has_vector and d.get('df_firmas') is not None:
                with sub_tabs[tab_idx]:
                    cobs = d['df_firmas']['Cobertura'].unique()
                    st.markdown("### Firmas espectrales generales")
                    if tipo_datos_sesion == "Multiespectral (dron/satélite)":
                        col_gen1, col_gen2 = st.columns(2)
                        with col_gen1:
                            if d.get('fig_gen_uas') is not None:
                                st.plotly_chart(d['fig_gen_uas'], width="stretch", config={'toImageButtonOptions': {'format': 'png'}}, key=f"line_uas_{name}")
                                custom_download_button(d['buf_gen_uas'], f"Firmas_UAS_{name}.png")
                        with col_gen2:
                            if d.get('fig_gen_sat') is not None:
                                st.plotly_chart(d['fig_gen_sat'], width="stretch", config={'toImageButtonOptions': {'format': 'png'}}, key=f"line_sat_{name}")
                                custom_download_button(d['buf_gen_sat'], f"Firmas_{sat_name_sesion}_{name}.png")
                    else:
                        if d.get('fig_gen_hs') is not None:
                            col_vacia1, col_centro, col_vacia2 = st.columns([1, 6, 1])
                            with col_centro:
                                st.plotly_chart(d['fig_gen_hs'], width="stretch", config={'toImageButtonOptions': {'format': 'png'}}, key=f"line_hs_{name}")
                                custom_download_button(d['buf_gen_hs'], f"Firmas_Hiperespectral_{name}.png")

                    st.markdown("---")
                    st.markdown("### Análisis individual por cobertura")
                    cols = st.columns(3)
                    for i, c in enumerate(cobs):
                        if c in d['pre_p_f']:
                            with cols[i % 3]:
                                st.plotly_chart(d['pre_p_f'][c], width="stretch", config={'toImageButtonOptions': {'format': 'png', 'filename': f'Firma_{c}'}}, key=f"ind_{name}_{c}")
                                custom_download_button(d['pre_p_plt'][c], f"Firma_{c}_{name}.png")

                    with st.expander("Centro de descargas (matrices numéricas)", expanded=False):
                        col_dl1, col_dl2, col_dl3 = st.columns(3)
                        with col_dl1: custom_download_button(d['df_firmas'].to_csv(index=False).encode('utf-8'), f"firmas_{name}.csv", text="Descargar firmas (CSV)", mime="text/csv")
                        if not d['df_corr'].empty:
                            with col_dl2: custom_download_button(d['df_corr'].to_csv(index=False).encode('utf-8'), f"correlacion_{name}.csv", text="Descargar correlación (CSV)", mime="text/csv")
                        if d.get('df_indices') is not None and not d['df_indices'].empty:
                            with col_dl3: custom_download_button(d['df_indices'].to_csv(index=False).encode('utf-8'), f"indices_{name}.csv", text="Descargar índices (CSV)", mime="text/csv")
                tab_idx += 1
                
                if tipo_datos_sesion == "Multiespectral (dron/satélite)":
                    with sub_tabs[tab_idx]:
                        st.subheader("Distribución estadística de índices espectrales por cobertura")
                        df_ind = d.get('df_indices')
                        if df_ind is not None and not df_ind.empty:
                            indices_disp = df_ind['Índice'].unique()
                            idx_sel = st.selectbox("Seleccione el índice a analizar:", indices_disp, key=f"sel_idx_{name}")
                            df_ind_filt = df_ind[df_ind['Índice'] == idx_sel]
                            
                            fig_box = px.box(df_ind_filt, x="Cobertura", y="Valor", color="Sensor", title=f"Índice {idx_sel}", color_discrete_map={'Uas (10m)': '#1f77b4', 'Uas (nativo)': '#2ca02c', sat_name_sesion: '#8c564b'})
                            fig_box.update_layout(template="simple_white", plot_bgcolor='white', legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None))
                            fig_box.update_xaxes(showgrid=True, gridcolor='LightGray')
                            fig_box.update_yaxes(showgrid=True, gridcolor='LightGray')

                            c_box_plot, c_box_dl = st.columns([4, 1])
                            with c_box_plot: st.plotly_chart(fig_box, width="stretch", config={'toImageButtonOptions': {'format': 'png'}}, key=f"box_{name}_{idx_sel}")
                            with c_box_dl: 
                                st.write(" "); st.write(" ")
                                if idx_sel in d['idx_buffers']:
                                    custom_download_button(d['idx_buffers'][idx_sel], f"Boxplot_{idx_sel}_{name}.png")

                            st.markdown(f"**Promedio calculado de {idx_sel} por cobertura**")
                            df_mean = df_ind_filt.groupby(['Cobertura', 'Sensor'])['Valor'].mean().reset_index()
                            df_pivot = df_mean.pivot(index='Cobertura', columns='Sensor', values='Valor').round(3)
                            st.dataframe(df_pivot, width="stretch")
                            
                            st.markdown("---")
                            st.subheader(f"Relación Dron vs Satélite: {idx_sel}")
                            df_corr_idx = d.get('df_corr_idx')
                            if df_corr_idx is not None and not df_corr_idx.empty:
                                df_c_idx_filt = df_corr_idx[df_corr_idx['Índice'] == idx_sel]
                                if not df_c_idx_filt.empty and len(df_c_idx_filt) > 2:
                                    mod_idx, r2_idx = calcular_regresion_limpia(df_c_idx_filt)
                                    fig_idx = px.scatter(df_c_idx_filt, x="Uas", y="Sat", color="Cobertura", title=f"Dispersión {idx_sel} (r²={r2_idx:.3f})", color_discrete_map=st.session_state.color_map)
                                    x_range_idx = pd.DataFrame({'Uas': [df_c_idx_filt['Uas'].min(), df_c_idx_filt['Uas'].max()]})
                                    fig_idx.add_trace(go.Scatter(x=x_range_idx['Uas'], y=mod_idx.predict(x_range_idx), mode='lines', name='Tendencia', line=dict(color='black', width=2, dash='dot')))
                                    fig_idx.update_layout(template="simple_white", plot_bgcolor='white', legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None), margin=dict(l=10, r=10, t=40, b=80))
                                    fig_idx.update_xaxes(showgrid=True, gridcolor='LightGray'); fig_idx.update_yaxes(showgrid=True, gridcolor='LightGray')
                                    
                                    c_scat_plot, c_scat_dl = st.columns([4, 1])
                                    with c_scat_plot: st.plotly_chart(fig_idx, width="stretch", config={'toImageButtonOptions': {'format': 'png'}}, key=f"scat_idx_{name}_{idx_sel}")
                                    with c_scat_dl:
                                        st.write(" "); st.write(" ")
                                        if idx_sel in d['idx_scat_buffers']:
                                            custom_download_button(d['idx_scat_buffers'][idx_sel], f"Dispersion_{idx_sel}_{name}.png")
                                else: st.info("No hay suficientes datos superpuestos para generar la regresión de este índice.")
                        else: st.info("No se han registrado índices para el cálculo.")
                    tab_idx += 1

                    with sub_tabs[tab_idx]:
                        st.subheader(f"Validación y ajuste radiométrico (Bandas Espectrales): {name}")
                        if d['has_sat'] and not d['df_corr'].empty:
                            bandas_disp = d['df_corr']['Banda'].unique()
                            bandas_sel = st.multiselect("Filtrar bandas para el cálculo de coeficiente de determinación (r²):", options=bandas_disp, default=bandas_disp, key=f"ms_r2_{name}")
                            df_corr_filt = d['df_corr'][d['df_corr']['Banda'].isin(bandas_sel)]
                            if not df_corr_filt.empty:
                                r2_list_escena = []
                                for c in cobs:
                                    df_sub = df_corr_filt[df_corr_filt['Cobertura'] == c]
                                    if len(df_sub) > 2: 
                                        _, r2_val = calcular_regresion_limpia(df_sub)
                                        r2_list_escena.append({'Cobertura': c, 'R2': r2_val})
                                if r2_list_escena:
                                    df_r2 = pd.DataFrame(r2_list_escena)
                                    fig_r2 = px.bar(df_r2, x='Cobertura', y='R2', color='R2', color_continuous_scale='PuBuGn', title="Ajuste radiométrico general (escena actual)")
                                    mean_r2 = df_r2['R2'].mean()
                                    fig_r2.add_hline(y=mean_r2, line_dash="dash", line_color="#d62728", annotation_text=f"Promedio: {mean_r2:.3f}", annotation_position="top right")
                                    fig_r2.update_layout(template="simple_white")
                                    
                                    c_r2_bar, c_r2_dl = st.columns([4,1])
                                    with c_r2_bar: st.plotly_chart(fig_r2, width="stretch", config={'toImageButtonOptions': {'format': 'png', 'filename': 'R2_Escena'}}, key=f"bar_r2_{name}")
                                    with c_r2_dl:
                                        st.write(" "); st.write(" ")
                                        fig_b, ax_b = plt.subplots(figsize=(8, 5), dpi=300)
                                        df_r2.set_index('Cobertura')['R2'].plot(kind='bar', ax=ax_b, color='#1f77b4')
                                        ax_b.axhline(y=mean_r2, color='red', linestyle='--', label=f'Promedio ({mean_r2:.3f})')
                                        ax_b.set_title(f"Comparación R² por cobertura - {name}", weight='bold')
                                        ax_b.set_ylabel("R²")
                                        ax_b.legend(frameon=True, facecolor='white', edgecolor='black')
                                        plt.tight_layout()
                                        buf_b = io.BytesIO(); fig_b.savefig(buf_b, format="png", bbox_inches='tight'); plt.close(fig_b)
                                        custom_download_button(buf_b.getvalue(), f"R2_Barplot_{name}.png")

                                st.markdown("**Regresiones lineales por cobertura**")
                                cols = st.columns(3)
                                for i, c in enumerate(cobs):
                                    df_sub = df_corr_filt[df_corr_filt['Cobertura'] == c]
                                    if len(df_sub) > 2:
                                        mod_g, r2_g = calcular_regresion_limpia(df_sub)
                                        fig_c = px.scatter(df_sub, x="Uas", y="Sat", color="Banda", title=f"{c} (r²={r2_g:.3f})")
                                        x_range = pd.DataFrame({'Uas': [df_sub['Uas'].min(), df_sub['Uas'].max()]})
                                        fig_c.add_trace(go.Scatter(x=x_range['Uas'], y=mod_g.predict(x_range), mode='lines', name='Tendencia', line=dict(color='black', width=2, dash='dot')))
                                        fig_c.update_layout(template="simple_white", plot_bgcolor='white', legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None), margin=dict(l=10, r=10, t=40, b=80))
                                        fig_c.update_xaxes(showgrid=True, gridcolor='LightGray'); fig_c.update_yaxes(showgrid=True, gridcolor='LightGray')
                                        with cols[i%3]: 
                                            st.plotly_chart(fig_c, width="stretch", config={'toImageButtonOptions': {'format': 'png'}}, key=f"scat_{name}_{c}")
                                            if c in d.get('reg_buffers', {}):
                                                custom_download_button(d['reg_buffers'][c], f"Regresion_Bandas_{c}_{name}.png")
                            else: st.warning("Seleccione al menos una banda espectral para procesar la estadística comparativa.")

    # --- Pestaña comparación global ---
    if has_vector and len(names) > 0:
        with tabs[-1]:
            st.header("Análisis comparativo global multiescena")
            
            if 'df_global_all_f' not in st.session_state:
                with st.spinner("Compilando análisis global..."):
                    all_f = pd.concat([st.session_state.data_escenas[n]['df_firmas'].assign(Escena=n) for n in names if 'df_firmas' in st.session_state.data_escenas[n]])
                    all_c_list = [st.session_state.data_escenas[n]['df_corr'].assign(Escena=n) for n in names if st.session_state.data_escenas[n]['has_sat'] and st.session_state.data_escenas[n]['has_uas'] and 'df_corr' in st.session_state.data_escenas[n] and not st.session_state.data_escenas[n]['df_corr'].empty]
                    all_c = pd.concat(all_c_list) if all_c_list else None
                    
                    st.session_state['df_global_all_f'] = all_f
                    st.session_state['df_global_all_c'] = all_c
                    st.session_state['global_buffers'] = pre_generar_graficos_globales(all_f, all_c, sat_name_sesion, tipo_datos_sesion, st.session_state.color_map)
            
            all_f = st.session_state['df_global_all_f']
            all_c = st.session_state['df_global_all_c']
            glob_buf = st.session_state['global_buffers']
            cobs = all_f['Cobertura'].unique()

            y_min_g = all_f['Reflectancia'].min()
            y_max_g = all_f['Reflectancia'].max()
            y_padding_g = (y_max_g - y_min_g) * 0.05
            y_range_g = [max(0, y_min_g - y_padding_g), y_max_g + y_padding_g]

            if tipo_datos_sesion == "Multiespectral (dron/satélite)":
                gt1, gt2, gt3 = st.tabs(["Evolución UAS", "Evolución satélite", "Resumen de ajuste global (r²)"])
                with gt1:
                    cols = st.columns(3)
                    for i, c in enumerate(cobs):
                        df_c = all_f[(all_f['Cobertura'] == c) & (all_f['Sensor'] == 'Uas (nativo)')]
                        if not df_c.empty:
                            fig = px.line(df_c, x="Banda", y="Reflectancia", color="Escena", markers=True, title=f"Uas nativo: {c}")
                            fig.update_traces(line=dict(width=2), marker=dict(size=8))
                            fig.update_layout(template="simple_white", legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None), margin=dict(l=10, r=10, t=40, b=80))
                            fig.update_xaxes(categoryorder='array', categoryarray=["Azul", "Verde", "Rojo", "Red edge", "Nir", "Swir 1", "Swir 2"], showgrid=True, gridcolor='LightGray')
                            fig.update_yaxes(range=y_range_g, showgrid=True, gridcolor='LightGray')
                            with cols[i % 3]: 
                                st.plotly_chart(fig, width="stretch", config={'toImageButtonOptions': {'format': 'png'}}, key=f"glob_uas_{c}")
                                if f'buf_glob_uas_{c}' in glob_buf:
                                    custom_download_button(glob_buf[f'buf_glob_uas_{c}'], f"Evolucion_UAS_{c}.png")
                with gt2:
                    cols = st.columns(3)
                    for i, c in enumerate(cobs):
                        df_c = all_f[(all_f['Cobertura'] == c) & (all_f['Sensor'] == sat_name_sesion)]
                        if not df_c.empty:
                            fig = px.line(df_c, x="Banda", y="Reflectancia", color="Escena", markers=True, title=f"Satélite: {c}")
                            fig.update_traces(line=dict(width=2), marker=dict(size=8))
                            fig.update_layout(template="simple_white", legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None), margin=dict(l=10, r=10, t=40, b=80))
                            fig.update_xaxes(categoryorder='array', categoryarray=["Azul", "Verde", "Rojo", "Red edge", "Nir", "Swir 1", "Swir 2"], showgrid=True, gridcolor='LightGray')
                            fig.update_yaxes(range=y_range_g, showgrid=True, gridcolor='LightGray')
                            with cols[i % 3]: 
                                st.plotly_chart(fig, width="stretch", config={'toImageButtonOptions': {'format': 'png'}}, key=f"glob_sat_{c}")
                                if f'buf_glob_sat_{c}' in glob_buf:
                                    custom_download_button(glob_buf[f'buf_glob_sat_{c}'], f"Evolucion_SAT_{c}.png")
                with gt3:
                    if all_c is not None:
                        bandas_disp_glob = all_c['Banda'].unique()
                        bandas_sel_glob = st.multiselect("Filtrar bandas para el cálculo global (r²):", options=bandas_disp_glob, default=bandas_disp_glob, key="ms_r2_glob")
                        all_c_filt = all_c[all_c['Banda'].isin(bandas_sel_glob)]
                        if not all_c_filt.empty:
                            r2_list = []
                            for n in names:
                                df_esc = all_c_filt[all_c_filt['Escena'] == n]
                                for c in cobs:
                                    df_sub = df_esc[df_esc['Cobertura'] == c]
                                    if len(df_sub) > 2:
                                        _, r2_val = calcular_regresion_limpia(df_sub)
                                        r2_list.append({'Escena': n, 'Cobertura': c, 'R2': r2_val})
                            if r2_list:
                                df_r2_glob = pd.DataFrame(r2_list)
                                fig_r2_glob = px.bar(df_r2_glob, x='Cobertura', y='R2', color='Escena', barmode='group', title="Comparación r² por cobertura y escena", color_discrete_sequence=px.colors.sequential.PuBuGn[2:])
                                promedio_total = df_r2_glob['R2'].mean()
                                fig_r2_glob.add_hline(y=promedio_total, line_dash="dash", line_color="#d62728", annotation_text=f"Promedio global: {promedio_total:.3f}", annotation_position="top right")
                                fig_r2_glob.update_layout(template="simple_white")
                                
                                c_g_r2, c_g_r2_dl = st.columns([4,1])
                                with c_g_r2: st.plotly_chart(fig_r2_glob, width="stretch", config={'toImageButtonOptions': {'format': 'png', 'filename': 'R2_Global'}}, key="glob_bar_r2")
                                with c_g_r2_dl:
                                    st.write(" "); st.write(" ")
                                    if 'buf_glob_bar_r2' in glob_buf:
                                        custom_download_button(glob_buf['buf_glob_bar_r2'], "R2_Global_Barplot.png")

                                st.markdown("### Regresiones consolidadas globales por cobertura")
                                cols = st.columns(3)
                                for i, c in enumerate(cobs):
                                    df_sub = all_c_filt[all_c_filt['Cobertura'] == c]
                                    if len(df_sub) > 2:
                                        mod_g, r2_g = calcular_regresion_limpia(df_sub)
                                        fig = px.scatter(df_sub, x="Uas", y="Sat", color="Escena", title=f"{c} (r² general = {r2_g:.3f})")
                                        x_range = pd.DataFrame({'Uas': [df_sub['Uas'].min(), df_sub['Uas'].max()]})
                                        fig.add_trace(go.Scatter(x=x_range['Uas'], y=mod_g.predict(x_range), mode='lines', name='Tendencia global', line=dict(color='black', width=2, dash='dot')))
                                        fig.update_layout(template="simple_white", plot_bgcolor='white', legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None), margin=dict(l=10, r=10, t=40, b=80))
                                        fig.update_xaxes(showgrid=True, gridcolor='LightGray'); fig.update_yaxes(showgrid=True, gridcolor='LightGray')
                                        with cols[i % 3]: 
                                            st.plotly_chart(fig, width="stretch", config={'toImageButtonOptions': {'format': 'png'}}, key=f"glob_scat_{c}")
                                            if f'buf_glob_scat_{c}' in glob_buf:
                                                custom_download_button(glob_buf[f'buf_glob_scat_{c}'], f"Regresion_Global_{c}.png")
                        else: st.warning("Seleccione al menos una banda espectral para procesar la estadística comparativa.")
            else:
                 gt1 = st.tabs(["Evolución de firmas hiperespectrales"])[0]
                 with gt1:
                     cols = st.columns(3)
                     for i, c in enumerate(cobs):
                         df_c = all_f[(all_f['Cobertura'] == c) & (all_f['Sensor'] == sat_name_sesion)].copy()
                         if not df_c.empty:
                             df_c['Wavelength'] = df_c['Banda'].astype(str).str.extract(r'(\d+)').astype(float)
                             x_col = "Wavelength" if not df_c['Wavelength'].isnull().all() else "idx_real"
                             df_c = df_c.sort_values(['Escena', x_col])
                             fig = px.line(df_c, x=x_col, y="Reflectancia", color="Escena", markers=False, title=f"Evolución hiperespectral: {c}")
                             fig.update_layout(template="simple_white", legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None), margin=dict(l=10, r=10, t=40, b=80))
                             fig.update_xaxes(showgrid=True, gridcolor='LightGray', title="Longitud de onda (nm)" if x_col == "Wavelength" else "Banda")
                             fig.update_yaxes(range=y_range_g, showgrid=True, gridcolor='LightGray')
                             add_spectral_bands_plotly(fig)
                             with cols[i % 3]: 
                                 st.plotly_chart(fig, width="stretch", config={'toImageButtonOptions': {'format': 'png'}}, key=f"glob_hs_{c}")
                                 if f'buf_glob_hs_{c}' in glob_buf:
                                     custom_download_button(glob_buf[f'buf_glob_hs_{c}'], f"Evolucion_HS_{c}.png")

            with st.expander("Centro de descargas (consolidado global)", expanded=False):
                col_c1, col_c2 = st.columns(2)
                with col_c1: custom_download_button(all_f.to_csv(index=False).encode('utf-8'), "firmas_globales.csv", text="Descargar firmas globales (CSV)", mime="text/csv")
                if tipo_datos_sesion == "Multiespectral (dron/satélite)" and all_c is not None:
                    with col_c2: custom_download_button(all_c.to_csv(index=False).encode('utf-8'), "correlaciones_globales.csv", text="Descargar correlaciones globales (CSV)", mime="text/csv")
else:
    # --- Pantalla de inicio ---
    st.markdown("### Plataforma de Validación Espectral y Multitemporal")
    st.markdown("Esta herramienta computacional ha sido desarrollada como solución metodológica para la validación y calibración cruzada de datos espaciales. Ante la incertidumbre en la fiabilidad de las imágenes capturadas por sensores montados en VANTs (drones comerciales como MicaSense o Sentera), esta plataforma utiliza la rigurosidad radiométrica de plataformas satelitales (como Sentinel-2) como 'verdad espacial' para confirmar la integridad de los datos.")
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1: 
        st.info("**1. Multiespectral (dron vs satélite)**\n\nEl flujo de trabajo principal. Ideal para extraer índices ecosistémicos (NDVI, MNDWI, SAVI) y generar modelos de regresión lineal ($R^2$) que certifiquen la correspondencia entre el vuelo del dron y la escena satelital.")
    with col2: 
        st.success("**2. Hiperespectral puro**\n\nDesbloquea el análisis de datos masivos. Omite la creación de índices básicos y se enfoca en entregar el espectro electromagnético continuo mediante un explorador de barrido espacial.")
    st.markdown("---")
    
    st.markdown("#### Guía Metodológica de Uso")
    st.markdown("""
    * **1. Preparación Vectorial:** Para operar la estadística automatizada, cargue un archivo vectorial (`.zip` con shapefile o `.gpkg`) que contenga un atributo de texto identificando las coberturas (ej. agua, vegetación, suelo).
    * **2. Ajuste Radiométrico:** Al trabajar con Sentinel-2 extraído de Google Earth Engine, recuerde que el offset suele ser 0 y la escala 10000. Configure correctamente la escala y offset de la ortofoto de su dron para que ambos sensores grafiquen entre 0 y 1.
    * **3. Configuración de Bandas:** Asigne el número de banda correcto según su sensor (MicaSense, Sentera, etc.). Si su sensor no posee una banda específica (ej. SWIR), ingrese **0**.
    * **4. Interpretación de Resultados:** La plataforma generará automáticamente firmas espectrales comparativas y gráficos de dispersión. Un $R^2$ cercano a 1.0 valida la fiabilidad radiométrica de la captura del dron respecto al satélite.
    * **5. Descarga de Informes:** Todos los gráficos poseen un botón estandarizado para descargar la imagen en alta resolución (PNG), lista para anexar a sus reportes y documentos.
    """)
