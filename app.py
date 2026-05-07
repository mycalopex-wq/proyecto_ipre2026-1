# -*- coding: utf-8 -*-
import streamlit as st
import rasterio
from rasterio.io import MemoryFile
import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.mask import mask
import tempfile, zipfile, os, re, io
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.transform import from_bounds
import folium
from streamlit_folium import st_folium
import plotly.express as px
import plotly.graph_objects as go
import random
from shapely.geometry import Point, box
import matplotlib.pyplot as plt
from matplotlib_scalebar.scalebar import ScaleBar
import contextily as cx

st.set_page_config(page_title="Plataforma de análisis espacial", layout="wide")
st.title("Plataforma de análisis espacial y multitemporal")

DOG_GIF_URL = "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExYmZlZHV1djJ4NnVuNWRod2JweGIwY3ZoamZkdnV2bGQ3ZXpxcG84MyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/f9vsEmv4NA9ry/giphy.gif"

# -----------------------------
# 1. FUNCIONES PRINCIPALES
# -----------------------------
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
    elif uploaded_file.name.endswith('.gpkg'):
        temp_gpkg = tempfile.NamedTemporaryFile(delete=False, suffix=".gpkg")
        temp_gpkg.write(uploaded_file.getvalue())
        temp_gpkg.close()
        return temp_gpkg.name
    return None

@st.cache_data
def load_vector_preview(vector_file):
    path = process_vector_file(vector_file)
    return gpd.read_file(path)

@st.cache_data
def reproject_raster(in_path, target_crs_str):
    target_crs = rasterio.crs.CRS.from_string(target_crs_str)
    with rasterio.open(in_path) as src:
        if src.crs == target_crs: return in_path 
        transform, width, height = calculate_default_transform(src.crs, target_crs, src.width, src.height, *src.bounds)
        kwargs = src.meta.copy()
        kwargs.update({"crs": target_crs, "transform": transform, "width": width, "height": height, "compress": 'lzw', "tiled": True, "num_threads": -1})
        reproj_path = tempfile.NamedTemporaryFile(delete=False, suffix=".tif").name
        with rasterio.open(reproj_path, "w", **kwargs) as dst:
            for i in range(1, src.count + 1):
                reproject(source=rasterio.band(src, i), destination=rasterio.band(dst, i),
                          src_transform=src.transform, src_crs=src.crs, dst_transform=transform, dst_crs=target_crs,
                          resampling=Resampling.nearest, num_threads=-1)
    return reproj_path

@st.cache_data
def resample_raster(in_path, target_res=10.0): 
    with rasterio.open(in_path) as src:
        if src.res[0] >= target_res: return in_path
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
                          resampling=Resampling.bilinear, num_threads=-1)
    return out_path

def add_cartographic_elements(ax, crs_is_metric, title):
    ax.set_title(title, pad=20, fontsize=14, color='black', weight='bold')
    ax.tick_params(axis='both', colors='black', labelsize=8)
    for spine in ax.spines.values():
        spine.set_color('black')
    ax.grid(color='black', linestyle='--', linewidth=0.5, alpha=0.2)
    ax.set_xlabel('Este (X)', color='black', fontsize=10)
    ax.set_ylabel('Norte (Y)', color='black', fontsize=10)
    if crs_is_metric:
        scalebar = ScaleBar(1, "m", length_fraction=0.2, location="lower right", color="black", box_color="white", box_alpha=0.8)
        ax.add_artist(scalebar)
    ax.text(0.05, 0.95, 'N\n↑', transform=ax.transAxes, color='black', fontsize=16, ha='center', va='center', weight='bold', bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=2))

def create_context_maps(ax_regional, ax_national, main_gdf):
    gdf_wm = main_gdf.to_crs(epsg=3857)
    gdf_wm.plot(ax=ax_regional, facecolor='none', edgecolor='red', linewidth=2)
    try:
        minx, miny, maxx, maxy = gdf_wm.total_bounds
        cx_coord, cy_coord = (minx + maxx) / 2, (miny + maxy) / 2
        buffer_reg_x, buffer_reg_y = 4000, 12000  
        ax_regional.set_xlim(cx_coord - buffer_reg_x, cx_coord + buffer_reg_x)
        ax_regional.set_ylim(cy_coord - buffer_reg_y, cy_coord + buffer_reg_y)
        cx.add_basemap(ax_regional, source=cx.providers.OpenStreetMap.Mapnik, zoom=12, alpha=0.7)
    except Exception: pass 
    centroid = gdf_wm.centroid
    centroid.plot(ax=ax_national, color='red', marker='*', markersize=300, edgecolor='black', linewidth=1.5, zorder=5)
    try:
        buffer_nat_x, buffer_nat_y = 250000, 750000 
        ax_national.set_xlim(cx_coord - buffer_nat_x, cx_coord + buffer_nat_x)
        ax_national.set_ylim(cy_coord - buffer_nat_y, cy_coord + buffer_nat_y)
        cx.add_basemap(ax_national, source=cx.providers.CartoDB.Positron, zoom=5, alpha=0.9)
    except Exception: pass
    
    for ax_map, title in zip([ax_regional, ax_national], ["Contexto regional", "Contexto país"]):
        ax_map.set_xticks([]); ax_map.set_yticks([])
        for spine in ax_map.spines.values(): spine.set_edgecolor('black'); spine.set_linewidth(1.5)
        ax_map.set_title(title, fontsize=11, weight='bold', color='black', pad=10)

def parse_scene_name(filename):
    match = re.search(r'^(\d{4}-\d{2}-\d{2})_([^_]+)', filename)
    if match:
        fecha = match.group(1)
        lugar = match.group(2).replace('-', ' ').title()
        return f"{lugar} ({fecha})"
    return os.path.splitext(filename)[0][:15]

# -----------------------------
# 2. MOTOR DE PROCESAMIENTO
# -----------------------------
def inicializar_base(uas_file, sat_file, master_crs, master_gdf, col_clase):
    data = {}
    t_uas_raw = tempfile.NamedTemporaryFile(delete=False, suffix=".tif")
    t_uas_raw.write(uas_file.getvalue()); t_uas_raw.close()
    t_uas_raw_name = reproject_raster(t_uas_raw.name, master_crs.to_string())
    data['uas_path_raw'] = t_uas_raw_name 
    data['uas_path_1m'] = resample_raster(t_uas_raw_name, target_res=1.0) 
    data['uas_path_10m'] = resample_raster(t_uas_raw_name, target_res=10.0) 
    
    with rasterio.open(data['uas_path_10m']) as src:
        gdf_cortado = gpd.clip(master_gdf, box(*src.bounds))
        if gdf_cortado.crs.is_geographic: gdf_area = gdf_cortado.to_crs(epsg=3857)
        else: gdf_area = gdf_cortado.copy()
        gdf_cortado['area_m2'] = gdf_area.geometry.area
        data['gdf'] = gdf_cortado
        data['gdf_diss'] = gdf_cortado.dissolve(by=col_clase, aggfunc={'area_m2': 'sum'}).reset_index()
        
    if sat_file is not None:
        t_sat = tempfile.NamedTemporaryFile(delete=False, suffix=".tif")
        t_sat.write(sat_file.getvalue()); t_sat.close()
        data['sat_clip_path'] = reproject_raster(t_sat.name, master_crs.to_string())
        data['has_sat'] = True
    else:
        data['has_sat'] = False
    return data

def calcular_firmas(data_dict, col_clase, sat_scale, sat_offset, b_idx, g_idx, r_idx, re_idx, n_idx, s_b_idx, s_g_idx, s_r_idx, s_re_idx, s_n_idx, sat_name):
    resultados, datos_correlacion = [], []
    uas_bands = {name for idx, name in [(b_idx,"Azul"), (g_idx,"Verde"), (r_idx,"Rojo"), (re_idx,"Red Edge"), (n_idx,"NIR")] if idx > 0}
    sat_bands = {name for idx, name in [(s_b_idx,"Azul"), (s_g_idx,"Verde"), (s_r_idx,"Rojo"), (s_re_idx,"Red Edge"), (s_n_idx,"NIR")] if idx > 0}
    bandas_comunes = uas_bands.intersection(sat_bands) if data_dict['has_sat'] else set()
    
    with rasterio.open(data_dict['uas_path_10m']) as uas_10m, rasterio.open(data_dict['uas_path_raw']) as uas_raw:
        sat_src = rasterio.open(data_dict['sat_clip_path']) if data_dict['has_sat'] else None
        for _, row in data_dict['gdf_diss'].iterrows():
            pts, bbox, intentos = [], row.geometry.bounds, 0
            while len(pts) < 100 and intentos < 2000:
                p = Point(random.uniform(bbox[0], bbox[2]), random.uniform(bbox[1], bbox[3]))
                if p.within(row.geometry): pts.append(p)
                intentos += 1
            if not pts: continue
            coordenadas = [(pt.x, pt.y) for pt in pts]
            
            # 1. Extraccion para firma nativa del dron
            muestras_uas_nat = np.array(list(uas_raw.sample(coordenadas))).astype(float)
            muestras_uas_nat[muestras_uas_nat <= 0] = np.nan
            firma_uas_nat = np.nanmean(muestras_uas_nat, axis=0)
            band_names_uas_map = {idx: name for idx, name in [(b_idx,"Azul"), (g_idx,"Verde"), (r_idx,"Rojo"), (re_idx,"Red Edge"), (n_idx,"NIR")] if idx > 0}
            for b in range(uas_raw.count):
                if (b+1) in band_names_uas_map: 
                    resultados.append({'Cobertura': row[col_clase], 'Banda': band_names_uas_map[b+1], 'Sensor': 'UAS (nativo)', 'Reflectancia': firma_uas_nat[b]})
            
            # 2. Extraccion para 10m (comparacion y R2)
            muestras_uas_10m = np.array(list(uas_10m.sample(coordenadas))).astype(float)
            muestras_uas_10m[muestras_uas_10m <= 0] = np.nan
            firma_uas_10m = np.nanmean(muestras_uas_10m, axis=0)
            for b in range(uas_10m.count):
                if (b+1) in band_names_uas_map: 
                    resultados.append({'Cobertura': row[col_clase], 'Banda': band_names_uas_map[b+1], 'Sensor': 'UAS (10m)', 'Reflectancia': firma_uas_10m[b]})
            
            if sat_src:
                muestras_sat_crudo = np.array(list(sat_src.sample(coordenadas))).astype(float)
                # Enmascarar ceros reales antes del offset para no distorsionar el "no data"
                muestras_sat_crudo[muestras_sat_crudo == 0] = np.nan
                # Aplicar la matematica corregida: (Valor + Offset) / Escala
                muestras_sat = (muestras_sat_crudo + sat_offset) / sat_scale
                
                mask_ambos = ~np.isnan(muestras_uas_10m).any(axis=1) & ~np.isnan(muestras_sat).any(axis=1)
                m_uas_filt, m_sat_filt = muestras_uas_10m[mask_ambos], muestras_sat[mask_ambos]
                
                firma_sat = np.nanmean(m_sat_filt, axis=0) if len(m_sat_filt) > 0 else np.nanmean(muestras_sat, axis=0)
                band_names_sat_map = {idx: name for idx, name in [(s_b_idx,"Azul"), (s_g_idx,"Verde"), (s_r_idx,"Rojo"), (s_re_idx,"Red Edge"), (s_n_idx,"NIR")] if idx > 0}
                for b in range(sat_src.count):
                    if (b+1) in band_names_sat_map: resultados.append({'Cobertura': row[col_clase], 'Banda': band_names_sat_map[b+1], 'Sensor': sat_name, 'Reflectancia': firma_sat[b]})
                
                for nb in bandas_comunes:
                    u_idx = {n: i for i, n in [(b_idx,"Azul"), (g_idx,"Verde"), (r_idx,"Rojo"), (re_idx,"Red Edge"), (n_idx,"NIR")] if i > 0}[nb] - 1
                    s_idx = {n: i for i, n in [(s_b_idx,"Azul"), (s_g_idx,"Verde"), (s_r_idx,"Rojo"), (s_re_idx,"Red Edge"), (s_n_idx,"NIR")] if i > 0}[nb] - 1
                    if u_idx < m_uas_filt.shape[1] and s_idx < m_sat_filt.shape[1]:
                        for uv, sv in zip(m_uas_filt[:, u_idx], m_sat_filt[:, s_idx]): 
                            datos_correlacion.append({'Cobertura': row[col_clase], 'Banda': nb, 'UAS': uv, 'SAT': sv})
                            
        if sat_src: sat_src.close()
    return pd.DataFrame(resultados), pd.DataFrame(datos_correlacion)

def pre_generar_plotly(df_firmas, sat_name):
    pre_firmas = {}
    if df_firmas.empty: return pre_firmas
    coberturas = df_firmas['Cobertura'].unique()

    df_comparacion = df_firmas[df_firmas['Sensor'].isin(['UAS (10m)', sat_name])]

    for cob in coberturas:
        df_f = df_comparacion[df_comparacion['Cobertura'] == cob]
        fig_f = px.line(df_f, x="Banda", y="Reflectancia", color="Sensor", markers=True, title=f"Firma espectral comparativa: {cob}", color_discrete_map={'UAS (10m)':'#1f77b4', sat_name:'#8c564b'})
        fig_f.update_traces(line=dict(width=2), marker=dict(size=8, symbol='circle'))
        fig_f.update_xaxes(categoryorder='array', categoryarray=["Azul", "Verde", "Rojo", "Red Edge", "NIR"], showgrid=True, gridcolor='LightGray')
        fig_f.update_yaxes(showgrid=True, gridcolor='LightGray') 
        fig_f.update_layout(template="simple_white", plot_bgcolor='white', legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None), margin=dict(l=10, r=10, t=40, b=80))
        pre_firmas[cob] = fig_f
    return pre_firmas

def generar_mapa_crudo(data_dict, sensor_sel, vis_mode, b_idx, g_idx, r_idx, re_idx, n_idx, s_b_idx, s_g_idx, s_r_idx, s_re_idx, s_n_idx, sat_scale, sat_offset, escena_name, banda_sel=1):
    is_sat = (sensor_sel == "Satélite")
    with rasterio.open(data_dict['uas_path_1m']) as base_src:
        ext = [base_src.bounds.left, base_src.bounds.right, base_src.bounds.bottom, base_src.bounds.top]
        uas_data = base_src.read()
        master_mask = (uas_data <= 0).all(axis=0)
        def obt_banda(idx_u, idx_s):
            out = np.full((base_src.height, base_src.width), np.nan, dtype=np.float32)
            if not is_sat: out = base_src.read(int(idx_u)).astype(float) if 0 < idx_u <= base_src.count else out
            else:
                if not data_dict.get('sat_clip_path'): return out
                with rasterio.open(data_dict['sat_clip_path']) as ss:
                    if 0 < idx_s <= ss.count: reproject(rasterio.band(ss, int(idx_s)), out, src_transform=ss.transform, src_crs=ss.crs, dst_transform=base_src.transform, dst_crs=base_src.crs, resampling=Resampling.bilinear)
                    no_data_mask = (out == 0)
                    out = (out + sat_offset) / sat_scale
                    out[no_data_mask] = np.nan
            out[master_mask] = np.nan
            return out
        def norm(arr):
            if np.isnan(arr).all(): return arr
            p2, p98 = np.nanpercentile(arr, [2, 98])
            return (np.clip(arr, p2, p98) - p2) / (p98 - p2 + 1e-6)
        fig = plt.figure(figsize=(12, 5.5), dpi=150); gs = fig.add_gridspec(1, 3, width_ratios=[3, 1, 1])
        ax, axr, axn = fig.add_subplot(gs[0]), fig.add_subplot(gs[1]), fig.add_subplot(gs[2])
        if vis_mode == "NDVI":
            rn, rr = obt_banda(n_idx, s_n_idx), obt_banda(r_idx, s_r_idx)
            ndvi = (rn - rr) / (rn + rr + 1e-6); p2, p98 = np.nanpercentile(ndvi, [2, 98])
            im = ax.imshow(ndvi, cmap='RdYlGn', vmin=p2, vmax=p98, extent=ext, interpolation='bicubic')
            fig.colorbar(im, ax=ax, shrink=0.7, pad=0.02).set_label('NDVI')
        elif "Color" in vis_mode or "RGB" in vis_mode:
            c1 = norm(obt_banda(n_idx, s_n_idx) if "Falso" in vis_mode else obt_banda(r_idx, s_r_idx))
            c2 = norm(obt_banda(r_idx, s_r_idx) if "Falso" in vis_mode else obt_banda(g_idx, s_g_idx))
            c3 = norm(obt_banda(g_idx, s_g_idx) if "Falso" in vis_mode else obt_banda(b_idx, s_b_idx))
            ax.imshow(np.dstack([np.nan_to_num(c1, nan=1.0), np.nan_to_num(c2, nan=1.0), np.nan_to_num(c3, nan=1.0), np.where(np.isnan(c1), 0, 1)]), extent=ext, interpolation='bicubic')
        elif "Banda individual" in vis_mode:
            b_norm = norm(obt_banda(banda_sel, banda_sel))
            ax.imshow(b_norm, cmap='gray', extent=ext, interpolation='bicubic')
        add_cartographic_elements(ax, True, f"{vis_mode} - {escena_name}"); create_context_maps(axr, axn, data_dict['gdf'])
        fig.subplots_adjust(left=0.02, right=0.98, wspace=0.1)
        buf = io.BytesIO(); fig.savefig(buf, format="png", bbox_inches='tight', facecolor='white'); plt.close(fig); return buf.getvalue()

def generar_todos_pre_mapas(data_dict, sat_scale, sat_offset, b_idx, g_idx, r_idx, re_idx, n_idx, s_b_idx, s_g_idx, s_r_idx, s_re_idx, s_n_idx, escena_name):
    pre_mapas = {}
    modos_pre = ["RGB (color real)", "Falso color (NIR-R-G)", "NDVI"]
    sensores_pre = ["UAS"]
    if data_dict.get('has_sat'): sensores_pre.append("Satélite")
    for sensor in sensores_pre:
        for modo in modos_pre:
            pre_mapas[f"{sensor}_{modo}"] = generar_mapa_crudo(data_dict, sensor, modo, b_idx, g_idx, r_idx, re_idx, n_idx, s_b_idx, s_g_idx, s_r_idx, s_re_idx, s_n_idx, sat_scale, sat_offset, escena_name)
    return pre_mapas

# -----------------------------
# 3. INTERFAZ (SIDEBAR)
# -----------------------------
with st.sidebar:
    st.header("Configuración del análisis")
    with st.expander("Archivo vectorial global", expanded=True):
        vector_file = st.file_uploader("Archivo vectorial", type=["zip", "gpkg"])
        if vector_file:
            preview_gdf = load_vector_preview(vector_file); st.session_state.raw_gdf = preview_gdf
            resumen_columnas = [{"Columna": c, "Ejemplos": ", ".join(map(str, preview_gdf[c].dropna().unique()[:3]))} for c in preview_gdf.columns if c != 'geometry']
            st.dataframe(pd.DataFrame(resumen_columnas), hide_index=True, width="stretch")
            st.session_state.col_clase = st.selectbox("Columna clase:", [c for c in preview_gdf.columns if c != 'geometry'], key='selector_clase')
            
    num_escenas = st.number_input("Cantidad de escenas", 1, 10, 1)
    archivos_escenas = []
    for i in range(1, num_escenas + 1):
        with st.expander(f"Archivos escena {i}"):
            archivos_escenas.append({"id": i, "uas": st.file_uploader(f"UAS {i}", type=["tif"]), "sat": st.file_uploader(f"SAT {i}", type=["tif"])})
    sat_name = st.text_input("Satélite", "Sentinel-2")
    
    # Nuevos inputs de escala y offset integrados
    sat_scale = st.number_input("Factor de escala", value=10000.0)
    sat_offset = st.number_input("Offset (desplazamiento)", value=-1000.0)
    
    c1, c2 = st.columns(2)
    with c1: u_b, u_g, u_r, u_re, u_n = st.number_input("U-B",1), st.number_input("U-G",2), st.number_input("U-R",3), st.number_input("U-RE",4), st.number_input("U-N",5)
    with c2: s_b, s_g, s_r, s_re, s_n = st.number_input("S-B",1), st.number_input("S-G",2), st.number_input("S-R",3), st.number_input("S-RE",4), st.number_input("S-N",5)
    
    if st.button("Ejecutar análisis espacial", width="stretch"):
        if 'col_clase' not in st.session_state:
            st.error("Por favor, sube un archivo vectorial primero.")
        else:
            with st.spinner("Preparando entorno..."):
                with MemoryFile(archivos_escenas[0]['uas'].getvalue()) as mem: master_crs = mem.open().crs
                raw_gdf = st.session_state.raw_gdf.to_crs(master_crs); st.session_state.master_gdf = raw_gdf; st.session_state.data_escenas = {}
                for e in archivos_escenas:
                    if e['uas'] is not None:
                        name = parse_scene_name(e['uas'].name)
                        db = inicializar_base(e['uas'], e['sat'], master_crs, raw_gdf, st.session_state.col_clase)
                        st.session_state.data_escenas[name] = db
                st.session_state.analisis_listo = True
                
    if st.button("Reiniciar entorno"): st.session_state.clear(); st.rerun()

# -----------------------------
# 5. RENDERIZADO PROGRESIVO
# -----------------------------
if st.session_state.get("analisis_listo") and 'col_clase' in st.session_state:
    col_clase_input = st.session_state.col_clase 
    names = list(st.session_state.data_escenas.keys())
    tabs = st.tabs([f"Análisis {n}" for n in names] + (["Comparación global"] if len(names)>0 else []))
    
    if 'color_map' not in st.session_state:
        unique_classes = st.session_state.master_gdf[col_clase_input].unique()
        palette = px.colors.qualitative.Plotly * 10 
        st.session_state.color_map = {c: palette[i] for i, c in enumerate(unique_classes)}

    for idx, name in enumerate(names):
        with tabs[idx]:
            d = st.session_state.data_escenas[name]
            st.subheader(f"Resultados: {name}")
            
            # --- MAPA Y TORTA ---
            col_mapa, col_torta = st.columns([2, 1])
            with col_mapa:
                gdf_map = d['gdf'].to_crs(epsg=4326)
                m = folium.Map(location=[gdf_map.total_bounds[[1,3]].mean(), gdf_map.total_bounds[[0,2]].mean()], zoom_start=15)
                folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google', name='Google Satellite').add_to(m)
                
                gdf_map["color"] = gdf_map[col_clase_input].map(st.session_state.color_map).fillna("#cccccc")
                folium.GeoJson(
                    gdf_map, 
                    style_function=lambda f: {'fillColor': f['properties']['color'], 'color': 'white', 'weight': 1, 'fillOpacity': 0.7},
                    tooltip=folium.GeoJsonTooltip(fields=[col_clase_input], aliases=['Cobertura:'], style="font-weight: bold; background-color: white;")
                ).add_to(m)
                st_folium(m, width=800, height=400, returned_objects=[], key=f"folium_{name}")

            with col_torta:
                df_stats = d['gdf_diss'].copy()
                st.metric("Total hectáreas", f"{df_stats['area_m2'].sum()/10000:.2f} ha")
                
                df_stats['label_text'] = df_stats.apply(lambda row: f"{row['area_m2']/10000:.2f} ha<br>{row['area_m2']:,.1f} m²", axis=1)
                fig_pie = px.pie(df_stats, values='area_m2', names=col_clase_input, hole=0.4, color=col_clase_input, color_discrete_map=st.session_state.color_map, custom_data=['label_text'])
                fig_pie.update_traces(hovertemplate="<b>%{label}</b><br>%{customdata[0]}")
                st.plotly_chart(fig_pie, width="stretch")

            # --- CARGA PROCESAMIENTO ---
            if 'pre_m' not in d:
                loading_ph = st.empty()
                with loading_ph.container():
                    st.markdown("<h3 style='text-align: center;'>Procesando escena espacial...</h3>", unsafe_allow_html=True)
                    col1, col2, col3 = st.columns([1,1,1]); col2.image(DOG_GIF_URL, width="stretch")
                    status_text, pbar = st.empty(), st.progress(0)
                    status_text.info("Paso 1/3: Muestreo radiométrico Monte Carlo...")
                    df_f, df_c = calcular_firmas(d, col_clase_input, sat_scale, sat_offset, u_b, u_g, u_r, u_re, u_n, s_b, s_g, s_r, s_re, s_n, sat_name)
                    d['df_firmas'], d['df_corr'] = df_f, df_c; pbar.progress(33)
                    status_text.info("Paso 2/3: Modelando firmas individuales...")
                    d['pre_p_f'] = pre_generar_plotly(df_f, sat_name); pbar.progress(66)
                    status_text.info("Paso 3/3: Renderizando mapas cartográficos...")
                    d['pre_m'] = generar_todos_pre_mapas(d, sat_scale, sat_offset, u_b, u_g, u_r, u_re, u_n, s_b, s_g, s_r, s_re, s_n, name); pbar.progress(100)
                st.session_state.data_escenas[name] = d; loading_ph.empty()

            # --- SUB-PESTAÑAS DE ESCENA ---
            sub_tabs = st.tabs(["Cartografía", "Análisis por cobertura", "Resumen de escena"])
            
            with sub_tabs[0]:
                s_sel = st.tabs(["UAS", "Satélite"]) if d['has_sat'] else [st.container()]
                for i, sensor in enumerate(["UAS", "Satélite"] if d['has_sat'] else ["UAS"]):
                    with s_sel[i]:
                        m_tabs = st.tabs(["RGB", "Falso color", "NDVI", "Banda individual"])
                        for j, m in enumerate(["RGB (color real)", "Falso color (NIR-R-G)", "NDVI"]):
                            with m_tabs[j]: 
                                st.image(d['pre_m'][f"{sensor}_{m}"], width="stretch")
                                st.download_button(label=f"Descargar mapa {m} (PNG)", data=d['pre_m'][f"{sensor}_{m}"], file_name=f"{sensor}_{m}.png", mime="image/png", key=f"dl_map_{name}_{sensor}_{m}")
                        with m_tabs[3]:
                            banda_sel = st.selectbox("Seleccione banda:", range(1, 6), key=f"bp_{name}_{sensor}")
                            mapa_puro = generar_mapa_crudo(d, sensor, "Banda individual", u_b, u_g, u_r, u_re, u_n, s_b, s_g, s_r, s_re, s_n, sat_scale, sat_offset, name, banda_sel)
                            st.image(mapa_puro, width="stretch")
            
            with sub_tabs[1]:
                cobs = d['df_firmas']['Cobertura'].unique()
                
                st.markdown("### Firmas espectrales generales")
                col_gen1, col_gen2 = st.columns(2)
                
                with col_gen1:
                    df_uas_nat = d['df_firmas'][d['df_firmas']['Sensor'] == 'UAS (nativo)']
                    if not df_uas_nat.empty:
                        fig_todas_uas = px.line(df_uas_nat, x="Banda", y="Reflectancia", color="Cobertura", markers=True, title="Resolución nativa dron (UAS)")
                        fig_todas_uas.update_traces(line=dict(width=2), marker=dict(size=8))
                        fig_todas_uas.update_layout(template="simple_white", height=550, plot_bgcolor='white', legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None))
                        fig_todas_uas.update_xaxes(categoryorder='array', categoryarray=["Azul", "Verde", "Rojo", "Red Edge", "NIR"], showgrid=True, gridcolor='LightGray')
                        fig_todas_uas.update_yaxes(showgrid=True, gridcolor='LightGray')
                        st.plotly_chart(fig_todas_uas, use_container_width=True, config={'toImageButtonOptions': {'format': 'png'}})
                
                with col_gen2:
                    if d['has_sat']:
                        df_sat = d['df_firmas'][d['df_firmas']['Sensor'] == sat_name]
                        if not df_sat.empty:
                            fig_todas_sat = px.line(df_sat, x="Banda", y="Reflectancia", color="Cobertura", markers=True, title=f"Resolución {sat_name}")
                            fig_todas_sat.update_traces(line=dict(width=2), marker=dict(size=8))
                            fig_todas_sat.update_layout(template="simple_white", height=550, plot_bgcolor='white', legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None))
                            fig_todas_sat.update_xaxes(categoryorder='array', categoryarray=["Azul", "Verde", "Rojo", "Red Edge", "NIR"], showgrid=True, gridcolor='LightGray')
                            fig_todas_sat.update_yaxes(showgrid=True, gridcolor='LightGray')
                            st.plotly_chart(fig_todas_sat, use_container_width=True, config={'toImageButtonOptions': {'format': 'png'}})

                st.markdown("---")
                st.markdown("### Firmas comparativas por cobertura individual (escala homologada)")
                cols = st.columns(3)
                for i, c in enumerate(cobs):
                    with cols[i%3]: 
                        st.plotly_chart(d['pre_p_f'][c], width="stretch", config={'toImageButtonOptions': {'format': 'png', 'filename': f'Firma_{c}'}})
            
            with sub_tabs[2]:
                st.subheader(f"Resumen radiométrico: {name}")
                if d['has_sat'] and not d['df_corr'].empty:
                    bandas_disp = d['df_corr']['Banda'].unique()
                    bandas_sel = st.multiselect("Filtrar bandas para cálculo de coeficiente de determinación (R²):", options=bandas_disp, default=bandas_disp, key=f"ms_r2_{name}")
                    
                    df_corr_filt = d['df_corr'][d['df_corr']['Banda'].isin(bandas_sel)]
                    
                    if not df_corr_filt.empty:
                        r2_list_escena = []
                        for c in cobs:
                            df_sub = df_corr_filt[df_corr_filt['Cobertura'] == c]
                            if len(df_sub) > 2: 
                                mod = LinearRegression().fit(df_sub[['UAS']], df_sub['SAT'])
                                r2_list_escena.append({'Cobertura': c, 'R2': r2_score(df_sub['SAT'], mod.predict(df_sub[['UAS']]))})
                        
                        if r2_list_escena:
                            df_r2 = pd.DataFrame(r2_list_escena)
                            fig_r2 = px.bar(df_r2, x='Cobertura', y='R2', color='R2', color_continuous_scale='Blues', title="Ajuste radiométrico UAS vs satélite (escena actual)")
                            mean_r2 = df_r2['R2'].mean()
                            fig_r2.add_hline(y=mean_r2, line_dash="dash", line_color="#d62728", annotation_text=f"Promedio área: {mean_r2:.3f}", annotation_position="top right")
                            fig_r2.update_layout(template="simple_white")
                            st.plotly_chart(fig_r2, width="stretch", config={'toImageButtonOptions': {'format': 'png', 'filename': 'R2_Escena'}})
                        
                        st.markdown("**Regresiones lineales de la escena (filtradas)**")
                        cols = st.columns(3)
                        for i, c in enumerate(cobs):
                            df_sub = df_corr_filt[df_corr_filt['Cobertura'] == c]
                            if len(df_sub) > 2:
                                mod_g = LinearRegression().fit(df_sub[['UAS']], df_sub['SAT'])
                                r2_g = r2_score(df_sub['SAT'], mod_g.predict(df_sub[['UAS']]))
                                fig_c = px.scatter(df_sub, x="UAS", y="SAT", color="Banda", title=f"{c} (R²={r2_g:.3f})")
                                fig_c.add_trace(go.Scatter(x=[df_sub['UAS'].min(), df_sub['UAS'].max()], y=mod_g.predict([[df_sub['UAS'].min()], [df_sub['UAS'].max()]]), mode='lines', name='Tendencia', line=dict(color='black', width=2, dash='dot')))
                                fig_c.update_layout(template="simple_white", plot_bgcolor='white', legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None), margin=dict(l=10, r=10, t=40, b=80))
                                fig_c.update_xaxes(showgrid=True, gridcolor='LightGray'); fig_c.update_yaxes(showgrid=True, gridcolor='LightGray')
                                with cols[i%3]: 
                                    st.plotly_chart(fig_c, width="stretch", config={'toImageButtonOptions': {'format': 'png'}})
                    else:
                        st.warning("Seleccione al menos una banda para procesar la estadística comparativa.")
                            
            with st.expander("Centro de descargas (datos numéricos)", expanded=False):
                col_dl1, col_dl2 = st.columns(2)
                col_dl1.download_button("Descargar datos de firmas (CSV)", d['df_firmas'].to_csv(index=False).encode('utf-8'), f"firmas_{name}.csv", "text/csv")
                if not d['df_corr'].empty:
                    col_dl2.download_button("Descargar datos de correlación (CSV)", d['df_corr'].to_csv(index=False).encode('utf-8'), f"correlacion_{name}.csv", "text/csv")
                st.info("Para exportar los gráficos, utilice el botón de cámara situado en la esquina superior derecha de cada visualización.")

    # --- PESTAÑA COMPARACIÓN GLOBAL ---
    if len(names) > 0:
        with tabs[-1]:
            st.header("Análisis comparativo global")
            all_f = pd.concat([st.session_state.data_escenas[n]['df_firmas'].assign(Escena=n) for n in names])
            cobs = all_f['Cobertura'].unique()
            gt1, gt2, gt3 = st.tabs(["Evolución UAS", "Evolución satélite", "Resumen de ajuste (R²)"])

            with gt1:
                cols = st.columns(3)
                for i, c in enumerate(cobs):
                    df_c = all_f[(all_f['Cobertura']==c) & (all_f['Sensor']=='UAS (nativo)')]
                    fig = px.line(df_c, x="Banda", y="Reflectancia", color="Escena", markers=True, title=f"UAS nativo: {c}")
                    fig.update_traces(line=dict(width=2), marker=dict(size=8))
                    fig.update_layout(template="simple_white", legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None), margin=dict(l=10, r=10, t=40, b=80))
                    fig.update_xaxes(categoryorder='array', categoryarray=["Azul", "Verde", "Rojo", "Red Edge", "NIR"], showgrid=True, gridcolor='LightGray')
                    fig.update_yaxes(showgrid=True, gridcolor='LightGray')
                    with cols[i%3]: st.plotly_chart(fig, width="stretch", config={'toImageButtonOptions': {'format': 'png'}})
            
            with gt2:
                cols = st.columns(3)
                for i, c in enumerate(cobs):
                    df_c = all_f[(all_f['Cobertura']==c) & (all_f['Sensor']==sat_name)]
                    if not df_c.empty:
                        fig = px.line(df_c, x="Banda", y="Reflectancia", color="Escena", markers=True, title=f"Satélite: {c}")
                        fig.update_traces(line=dict(width=2), marker=dict(size=8))
                        fig.update_layout(template="simple_white", legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None), margin=dict(l=10, r=10, t=40, b=80))
                        fig.update_xaxes(categoryorder='array', categoryarray=["Azul", "Verde", "Rojo", "Red Edge", "NIR"], showgrid=True, gridcolor='LightGray')
                        fig.update_yaxes(showgrid=True, gridcolor='LightGray')
                        with cols[i%3]: st.plotly_chart(fig, width="stretch", config={'toImageButtonOptions': {'format': 'png'}})
            
            with gt3:
                all_c_list = [st.session_state.data_escenas[n]['df_corr'].assign(Escena=n) for n in names if st.session_state.data_escenas[n]['has_sat'] and not st.session_state.data_escenas[n]['df_corr'].empty]
                if all_c_list:
                    all_c = pd.concat(all_c_list)
                    
                    bandas_disp_glob = all_c['Banda'].unique()
                    bandas_sel_glob = st.multiselect("Filtrar bandas para cálculo global (R²):", options=bandas_disp_glob, default=bandas_disp_glob, key="ms_r2_glob")
                    all_c_filt = all_c[all_c['Banda'].isin(bandas_sel_glob)]
                    
                    if not all_c_filt.empty:
                        r2_list = []
                        for n in names:
                            df_esc = all_c_filt[all_c_filt['Escena'] == n]
                            for c in cobs:
                                df_sub = df_esc[df_esc['Cobertura'] == c]
                                if len(df_sub) > 2:
                                    mod = LinearRegression().fit(df_sub[['UAS']], df_sub['SAT'])
                                    r2_list.append({'Escena': n, 'Cobertura': c, 'R2': r2_score(df_sub['SAT'], mod.predict(df_sub[['UAS']]))})
                        
                        if r2_list:
                            df_r2_glob = pd.DataFrame(r2_list)
                            fig_r2_glob = px.bar(df_r2_glob, x='Cobertura', y='R2', color='Escena', barmode='group', title="Comparación R² por cobertura y escena")
                            promedio_total = df_r2_glob['R2'].mean()
                            fig_r2_glob.add_hline(y=promedio_total, line_dash="dash", line_color="#d62728", annotation_text=f"Promedio global total: {promedio_total:.3f}", annotation_position="top right")
                            fig_r2_glob.update_layout(template="simple_white")
                            st.plotly_chart(fig_r2_glob, width="stretch", config={'toImageButtonOptions': {'format': 'png', 'filename': 'R2_Global'}})
                            
                            st.markdown("### Regresiones consolidadas globales")
                            cols = st.columns(3)
                            for i, c in enumerate(cobs):
                                df_sub = all_c_filt[all_c_filt['Cobertura'] == c]
                                if len(df_sub) > 2:
                                    mod_g = LinearRegression().fit(df_sub[['UAS']], df_sub['SAT'])
                                    r2_g = r2_score(df_sub['SAT'], mod_g.predict(df_sub[['UAS']]))
                                    fig = px.scatter(df_sub, x="UAS", y="SAT", color="Escena", title=f"{c} (R² general = {r2_g:.3f})")
                                    fig.add_trace(go.Scatter(x=[df_sub['UAS'].min(), df_sub['UAS'].max()], y=mod_g.predict([[df_sub['UAS'].min()], [df_sub['UAS'].max()]]), mode='lines', name='Tendencia', line=dict(color='black', width=2, dash='dot')))
                                    fig.update_layout(template="simple_white", plot_bgcolor='white', legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, title=None), margin=dict(l=10, r=10, t=40, b=80))
                                    fig.update_xaxes(showgrid=True, gridcolor='LightGray'); fig.update_yaxes(showgrid=True, gridcolor='LightGray')
                                    with cols[i%3]: st.plotly_chart(fig, width="stretch", config={'toImageButtonOptions': {'format': 'png'}})
                    else:
                        st.warning("Seleccione al menos una banda para procesar la estadística comparativa.")
            
            with st.expander("Centro de descargas (consolidado global)", expanded=False):
                st.download_button("Descargar todas las firmas (CSV)", all_f.to_csv(index=False).encode('utf-8'), "firmas_globales.csv", "text/csv")
                if all_c_list:
                    st.download_button("Descargar todas las correlaciones (CSV)", all_c.to_csv(index=False).encode('utf-8'), "correlaciones_globales.csv", "text/csv")
