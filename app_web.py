import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from PIL import Image, ImageEnhance
from pyzbar.pyzbar import decode
from gspread_dataframe import set_with_dataframe, get_as_dataframe
import io
import json

st.set_page_config(page_title="App de Inventario", layout="centered", page_icon="📦")

@st.cache_resource
def conectar_google_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        creds_dict = json.loads(st.secrets["google_json"])
        credenciales = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        cliente = gspread.authorize(credenciales)
        libro = cliente.open("Inventario_Activo")
        return libro, True, ""
    except Exception as e:
        return None, False, str(e)

libro_bd, conexion_exitosa, error_msg = conectar_google_sheets()

# --- MEJORA: LIMPIEZA DE CÓDIGOS SÚPER ESTRICTA ---
def limpiar_codigo(val):
    if pd.isna(val): return ""
    # Si Sheets lo lee como número (ej. 84229488.0), le quitamos el decimal
    if isinstance(val, float) and val.is_integer(): return str(int(val))
    val_str = str(val).strip()
    if val_str.endswith('.0'): val_str = val_str[:-2]
    return val_str

def obtener_ronda_activa():
    try:
        return libro_bd.worksheet("Config").acell("B1").value
    except:
        return "Conteo 1"

st.title("📦 Inventario Agroequipos")

if not conexion_exitosa:
    st.error("❌ Error de conexión.")
    st.stop()

rol = st.sidebar.radio("Selecciona tu perfil:", ["📱 Capturista", "💻 Administrador"])

# ==========================================
# 📱 PERFIL: CAPTURISTA (PARA LOS CELULARES)
# ==========================================
if rol == "📱 Capturista":
    st.subheader("Modo Escáner")
    
    pestañas = [hoja.title for hoja in libro_bd.worksheets() if hoja.title != "Config"]
    if not pestañas:
        st.warning("⚠️ No hay almacenes cargados.")
        st.stop()
        
    almacen_seleccionado = st.selectbox("1️⃣ Selecciona el Almacén:", pestañas)
    hoja_actual = libro_bd.worksheet(almacen_seleccionado)
    
    ronda_conteo = obtener_ronda_activa()
    st.info(f"🔄 Capturando actualmente en: **{ronda_conteo}**")
    
    st.write("2️⃣ Escanea el producto o escribe el código")
    codigo_detectado = ""
    foto_camara = st.camera_input("📷 Usar cámara del celular")
    
    if foto_camara:
        imagen = Image.open(foto_camara)
        imagen_gris = imagen.convert('L')
        optimizador = ImageEnhance.Contrast(imagen_gris)
        imagen_mejorada = optimizador.enhance(2.5)
        
        codigos = decode(imagen_mejorada)
        if not codigos:
            imagen_rotada = imagen_mejorada.rotate(90, expand=True)
            codigos = decode(imagen_rotada)
            
        if codigos:
            codigo_detectado = codigos[0].data.decode('utf-8')
            st.success(f"✅ Código detectado en cámara: {codigo_detectado}")
        else:
            st.error("❌ No se detectó código. Intenta poner el teléfono en HORIZONTAL.")
            
    # --- MEJORA: FORMULARIO QUE SE LIMPIA SOLO AL GUARDAR ---
    with st.form("formulario_captura", clear_on_submit=True):
        st.write("3️⃣ Confirma el código y la cantidad:")
        codigo_manual = st.text_input("Código a registrar:", value=codigo_detectado)
        cantidad = st.number_input("Cantidad física contada:", min_value=0.0, step=1.0)
        
        boton_guardar = st.form_submit_button("💾 Guardar Conteo", type="primary", use_container_width=True)
        
        if boton_guardar:
            if not codigo_manual:
                st.warning("Falta el código de barras.")
            else:
                with st.spinner("Guardando en la nube..."):
                    # Obtenemos toda la hoja sin borrar filas para no perder el índice correcto
                    df = get_as_dataframe(hoja_actual)
                    col_codigo = next((c for c in df.columns if str(c).strip().lower() in ['código', 'codigo', 'cod']), None)
                    
                    if col_codigo:
                        df['_codigo_limpio'] = df[col_codigo].apply(limpiar_codigo)
                        codigo_buscado = limpiar_codigo(codigo_manual)
                        
                        if codigo_buscado in df['_codigo_limpio'].values:
                            # Ubicamos la fila exacta
                            indice_df = df[df['_codigo_limpio'] == codigo_buscado].index[0]
                            fila_gsheets = int(indice_df) + 2 
                            
                            if ronda_conteo not in df.columns:
                                col_escribir = len(df.columns) # Se agrega al final real de las columnas de datos
                                hoja_actual.update_cell(1, col_escribir, ronda_conteo)
                            else:
                                col_escribir = df.columns.get_loc(ronda_conteo) + 1
                            
                            valor_actual = hoja_actual.cell(fila_gsheets, col_escribir).value
                            valor_actual = float(valor_actual) if valor_actual else 0.0
                            nuevo_valor = valor_actual + cantidad
                            
                            hoja_actual.update_cell(fila_gsheets, col_escribir, nuevo_valor)
                            st.success(f"✔️ ¡Guardado exitoso! Se agregaron {cantidad} piezas al código {codigo_manual}. (Si usaste la cámara, ciérrala presionando la 'X' para escanear el siguiente).")
                        else:
                            st.error(f"❌ El código {codigo_manual} no existe en {almacen_seleccionado}.")
                    else:
                        st.error("❌ El archivo base no tiene una columna llamada 'Código'.")

# ==========================================
# 💻 PERFIL: ADMINISTRADOR (PARA TI)
# ==========================================
elif rol == "💻 Administrador":
    pin = st.text_input("Introduce el PIN secreto:", type="password")
    
    if pin == "1234":
        st.success("Acceso autorizado")
        
        st.subheader("⚙️ 1. Control de Rondas (Global)")
        ronda_actual = obtener_ronda_activa()
        st.info(f"Actualmente, todos los celulares están guardando en: **{ronda_actual}**")
        
        nueva_ronda = st.selectbox("Cambiar la ronda activa para todas las sucursales a:", ["Conteo 1", "Conteo 2", "Conteo 3", "Conteo 4"])
        if st.button("Actualizar Ronda para todos"):
            try:
                hoja_config = libro_bd.worksheet("Config")
            except:
                hoja_config = libro_bd.add_worksheet(title="Config", rows="2", cols="2")
                hoja_config.update_cell(1, 1, "Ronda Activa")
            hoja_config.update_cell(1, 2, nueva_ronda)
            st.success(f"¡Listo! Todos los celulares ahora guardarán en {nueva_ronda}")
            st.rerun()
        
        st.divider()
        
        st.subheader("📥 2. Cargar Base de Inventario")
        archivo_excel = st.file_uploader("Selecciona el archivo Excel (.xlsx)", type=['xlsx'])
        
        if archivo_excel:
            if st.button("Subir a Google Sheets (Borrará el inventario anterior)", type="primary"):
                with st.spinner("Procesando y subiendo a la nube..."):
                    xls = pd.ExcelFile(archivo_excel)
                    hoja_temp = libro_bd.add_worksheet(title="Temp_borrar", rows="1", cols="1")
                    
                    for hoja in libro_bd.worksheets():
                        if hoja.title != "Temp_borrar":
                            libro_bd.del_worksheet(hoja)
                            
                    hoja_config = libro_bd.add_worksheet(title="Config", rows="2", cols="2")
                    hoja_config.update_cell(1, 1, "Ronda Activa")
                    hoja_config.update_cell(1, 2, "Conteo 1")
                    
                    for nombre_hoja in xls.sheet_names:
                        df_hoja = pd.read_excel(xls, sheet_name=nombre_hoja)
                        nueva_hoja = libro_bd.add_worksheet(title=nombre_hoja, rows="1000", cols="20")
                        set_with_dataframe(nueva_hoja, df_hoja)
                        
                    libro_bd.del_worksheet(hoja_temp)
                    st.success("¡Base de datos actualizada! Los celulares ya pueden comenzar a capturar el Conteo 1.")

        st.divider()
        
        st.subheader("📤 3. Cerrar Inventario y Facturar")
        
        if st.button("Generar Excel de Cierre", type="primary"):
            with st.spinner("Calculando diferencias y precios..."):
                salida_excel = io.BytesIO()
                
                with pd.ExcelWriter(salida_excel, engine='openpyxl') as writer:
                    for hoja in libro_bd.worksheets():
                        if hoja.title == "Config":
                            continue
                            
                        df = get_as_dataframe(hoja)
                        col_codigo = next((c for c in df.columns if str(c).strip().lower() in ['código', 'codigo', 'cod']), None)
                        col_existencia = next((c for c in df.columns if str(c).strip().lower() == 'existencia'), None)
                        
                        if col_codigo:
                            df = df.dropna(subset=[col_codigo])
                        else:
                            df = df.dropna(how='all')
                            
                        cols_conteos = [c for c in df.columns if str(c).strip().lower().startswith('conteo')]
                        
                        # --- MEJORA: CÁLCULOS INDEPENDIENTES POR CADA CONTEO ---
                        if cols_conteos and col_existencia:
                            for c in cols_conteos:
                                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
                                # Genera "Dif Conteo 1", "Dif Conteo 2", etc.
                                dif_nombre = f"Dif {c}"
                                df[dif_nombre] = df[c] - pd.to_numeric(df[col_existencia], errors='coerce').fillna(0)
                                
                                col_costo = next((col for col in df.columns if str(col).strip().lower() == 'costo promedio'), None)
                                if col_costo:
                                    costo_val = pd.to_numeric(df[col_costo].astype(str).str.replace('$', '').str.replace(',', ''), errors='coerce').fillna(0)
                                    faltantes = df[dif_nombre].apply(lambda x: abs(x) if x < 0 else 0)
                                    
                                    precio_v_unitario = costo_val / 0.7
                                    df['precio unitario'] = precio_v_unitario.round(2)
                                    # Genera la facturación específica de ESE conteo
                                    df[f'Venta Faltante {c}'] = (precio_v_unitario * faltantes).round(2)
                                
                        df.to_excel(writer, sheet_name=hoja.title, index=False)
                
                st.balloons()
                st.success("¡Cálculos independientes terminados!")
                
                st.download_button(
                    label="⬇️ Descargar Reporte Final (.xlsx)",
                    data=salida_excel.getvalue(),
                    file_name="Inventario_FINAL.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary"
                )
    elif pin != "":
        st.error("PIN incorrecto.")
