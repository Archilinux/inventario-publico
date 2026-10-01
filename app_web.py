import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from PIL import Image, ImageEnhance
from pyzbar.pyzbar import decode
from gspread_dataframe import set_with_dataframe, get_as_dataframe
import io
import json

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="App de Inventario", layout="centered", page_icon="📦")

# --- CONEXIÓN A GOOGLE SHEETS ---

@st.cache_resource
def conectar_google_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        # Ahora lee la llave desde la bóveda secreta de Streamlit, no desde el archivo local
        creds_dict = json.loads(st.secrets["google_json"])
        credenciales = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        cliente = gspread.authorize(credenciales)
        libro = cliente.open("Inventario_Activo")
        return libro, True, ""
    except Exception as e:
        return None, False, str(e)

libro_bd, conexion_exitosa, error_msg = conectar_google_sheets()

# Funciones auxiliares para buscar columnas (igual que en tu programa de escritorio)
def limpiar_codigo(val):
    if pd.isna(val): return ""
    if isinstance(val, float) and val.is_integer(): return str(int(val))
    return str(val).strip().replace('.0', '')

# --- INTERFAZ PRINCIPAL ---
st.title("📦 Inventario Agroequipos")

if not conexion_exitosa:
    st.error("❌ No se pudo conectar a Google Sheets. Verifica que el archivo credenciales.json esté en la carpeta.")
    st.write(f"Error técnico: {error_msg}")
    st.stop()

# --- MENÚ DE ROLES ---
rol = st.sidebar.radio("Selecciona tu perfil:", ["📱 Capturista", "💻 Administrador"])

# ==========================================
# 📱 PERFIL: CAPTURISTA (PARA LOS CELULARES)
# ==========================================
if rol == "📱 Capturista":
    st.subheader("Modo Escáner")
    
    pestañas = [hoja.title for hoja in libro_bd.worksheets()]
    if not pestañas:
        st.warning("⚠️ No hay almacenes cargados.")
        st.stop()
        
    almacen_seleccionado = st.selectbox("1️⃣ Selecciona el Almacén:", pestañas)
    
    # --- NUEVO: SELECTOR DE RONDA DE CONTEO ---
    ronda_conteo = st.selectbox("2️⃣ Ronda de captura:", ["Conteo 1", "Conteo 2", "Conteo 3"])
    hoja_actual = libro_bd.worksheet(almacen_seleccionado)
    
    st.write("3️⃣ Escanea el producto o escribe el código")
    
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
            st.success(f"✅ Código detectado: {codigo_detectado}")
        else:
            st.error("❌ No se detectó código. Intenta poner el teléfono en HORIZONTAL.")
            
    codigo_manual = st.text_input("O escribe el código aquí:", value=codigo_detectado)
    cantidad = st.number_input("4️⃣ Cantidad física contada:", min_value=0.0, step=1.0)
    
    if st.button("💾 Guardar Conteo", type="primary", use_container_width=True):
        if not codigo_manual:
            st.warning("Falta el código de barras.")
        else:
            with st.spinner("Guardando en la nube..."):
                df = get_as_dataframe(hoja_actual).dropna(how='all')
                
                # Buscar columna de código sin importar mayúsculas
                col_codigo = next((c for c in df.columns if str(c).strip().lower() in ['código', 'codigo', 'cod']), None)
                
                if col_codigo:
                    df['_codigo_limpio'] = df[col_codigo].apply(limpiar_codigo)
                    codigo_buscado = limpiar_codigo(codigo_manual)
                    
                    if codigo_buscado in df['_codigo_limpio'].values:
                        indice_df = df[df['_codigo_limpio'] == codigo_buscado].index[0]
                        fila_gsheets = int(indice_df) + 2 
                        
                        df = df.drop(columns=['_codigo_limpio']) # Limpiar tabla temporal
                        
                        # Escribir en la columna de la ronda seleccionada (Ej. "Conteo 1")
                        if ronda_conteo not in df.columns:
                            col_escribir = len(df.columns) + 1
                            hoja_actual.update_cell(1, col_escribir, ronda_conteo)
                        else:
                            col_escribir = df.columns.get_loc(ronda_conteo) + 1
                        
                        valor_actual = hoja_actual.cell(fila_gsheets, col_escribir).value
                        valor_actual = float(valor_actual) if valor_actual else 0.0
                        nuevo_valor = valor_actual + cantidad
                        
                        hoja_actual.update_cell(fila_gsheets, col_escribir, nuevo_valor)
                        st.success(f"✔️ ¡Guardado! {cantidad} piezas en {ronda_conteo} para el código {codigo_manual}.")
                    else:
                        st.error(f"❌ El código {codigo_manual} no existe en {almacen_seleccionado}.")
                else:
                    st.error("❌ El archivo base no tiene una columna llamada 'Código'.")

# ==========================================
# 💻 PERFIL: ADMINISTRADOR (PARA TI)
# ==========================================
elif rol == "💻 Administrador":
    pin = st.text_input("Introduce el PIN secreto:", type="password")
    
    if pin == "AgroSA":
        st.success("Acceso autorizado")
        
        # SECCIÓN A: SUBIR EXCEL BASE
        st.subheader("📥 1. Cargar Base de Inventario")
        st.write("Sube el archivo Excel del sistema para iniciar un nuevo conteo.")
        archivo_excel = st.file_uploader("Selecciona el archivo Excel (.xlsx)", type=['xlsx'])
        
        if archivo_excel:
            if st.button("Subir a Google Sheets (Borrará el inventario anterior)", type="primary"):
                with st.spinner("Procesando y subiendo a la nube..."):
                    # Leer Excel local
                    xls = pd.ExcelFile(archivo_excel)
                    
                    # 1. Crear una hoja temporal para que el archivo nunca quede vacío
                    hoja_temp = libro_bd.add_worksheet(title="Temp_borrar", rows="1", cols="1")
                    
                    # 2. Borrar todas las hojas originales de forma segura
                    for hoja in libro_bd.worksheets():
                        if hoja.title != "Temp_borrar":
                            libro_bd.del_worksheet(hoja)
                            
                    # 3. Crear pestañas nuevas y subir tus datos
                    for nombre_hoja in xls.sheet_names:
                        df_hoja = pd.read_excel(xls, sheet_name=nombre_hoja)
                        # Creamos la hoja en Google Sheets
                        nueva_hoja = libro_bd.add_worksheet(title=nombre_hoja, rows="1000", cols="20")
                        # Pegamos los datos
                        set_with_dataframe(nueva_hoja, df_hoja)
                        
                    # 4. Finalmente, borrar la hoja temporal
                    libro_bd.del_worksheet(hoja_temp)
                        
                    st.success("¡Base de datos actualizada! Los celulares ya pueden comenzar a capturar.")


        st.divider()
        
        # SECCIÓN B: CIERRE Y REPORTE
        st.subheader("📤 2. Cerrar Inventario y Facturar")
        st.write("Genera el reporte final con Subtotales. (Puedes generar este reporte las veces que quieras, no bloquea el sistema).")
        
        if st.button("Generar Excel de Cierre", type="primary"):
            with st.spinner("Calculando diferencias y precios..."):
                salida_excel = io.BytesIO()
                
                with pd.ExcelWriter(salida_excel, engine='openpyxl') as writer:
                    for hoja in libro_bd.worksheets():
                        df = get_as_dataframe(hoja)
                        
                        # Buscar columnas importantes ignorando mayúsculas/minúsculas
                        col_codigo = next((c for c in df.columns if str(c).strip().lower() in ['código', 'codigo', 'cod']), None)
                        col_existencia = next((c for c in df.columns if str(c).strip().lower() == 'existencia'), None)
                        
                        # Limpiar filas vacías
                        if col_codigo:
                            df = df.dropna(subset=[col_codigo])
                        else:
                            df = df.dropna(how='all')
                            
                        # --- NUEVO: SUMAR TODOS LOS CONTEOS ---
                        # Identificar todas las columnas que empiecen con la palabra "conteo"
                        cols_conteos = [c for c in df.columns if str(c).strip().lower().startswith('conteo')]
                        
                        # Solo hacer la matemática si hay conteos Y encontró la columna de existencia
                        if cols_conteos and col_existencia:
                            # Asegurarse que son números
                            for c in cols_conteos:
                                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
                                
                            # Sumar las rondas en una columna Total
                            df['Total Conteo'] = df[cols_conteos].sum(axis=1)
                            
                            # La diferencia se calcula sobre el Total
                            df['dif'] = df['Total Conteo'] - pd.to_numeric(df[col_existencia], errors='coerce').fillna(0)
                            
                            # Calcular precios si existe el costo
                            col_costo = next((c for c in df.columns if str(c).strip().lower() == 'costo promedio'), None)
                            if col_costo:
                                costo_val = pd.to_numeric(df[col_costo].astype(str).str.replace('$', '').str.replace(',', ''), errors='coerce').fillna(0)
                                faltantes = df['dif'].apply(lambda x: abs(x) if x < 0 else 0)
                                
                                precio_v_unitario = costo_val / 0.7
                                df['precio unitario'] = precio_v_unitario.round(2)
                                df['precio venta'] = (precio_v_unitario * faltantes).round(2)
                                
                        df.to_excel(writer, sheet_name=hoja.title, index=False)
                        
                
                st.balloons()
                st.success("¡Cálculos terminados!")
                
                # Botón de descarga
                st.download_button(
                    label="⬇️ Descargar Reporte Final (.xlsx)",
                    data=salida_excel.getvalue(),
                    file_name="Inventario_FINAL.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary"
                )
