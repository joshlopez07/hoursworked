import streamlit as st
import requests
import datetime
import calendar
import json
import io
import holidays
from requests.auth import HTTPBasicAuth
from datetime import timedelta, timezone

# ==== CONFIGURACIÓN ====
organization = "cleveritcl"
project = "Servicios Staffing"  # sin %20
local_tz = timezone(timedelta(hours=-3))

# ==== INTERFAZ ====
st.title("Generador Automático de User Stories (Azure DevOps)")
st.write("Crea User Stories cerradas automáticamente usando tu PAT.")

# ==== FUNCIONES AUXILIARES ====
def find_feature_for_user(auth, organization, project, assigned_to, feature_title):
    """Usa WIQL para encontrar el ID de un Feature asignado a un usuario con un título específico."""
    wiql_url = f"https://dev.azure.com/{organization}/{project}/_apis/wit/wiql?api-version=7.1-preview.2"
    
    escaped_assigned_to = assigned_to.replace("'", "''")
    escaped_feature_title = feature_title.replace("'", "''")

    query = (
        "SELECT [System.Id] FROM WorkItems "
        f"WHERE [System.WorkItemType] = 'Feature' "
        f"AND [System.AssignedTo] = '{escaped_assigned_to}' "
        f"AND [System.Title] = '{escaped_feature_title}'"
    )
    
    wiql_body = {"query": query}
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(wiql_url, json=wiql_body, headers=headers, auth=auth)
        if response.status_code == 200:
            work_items = response.json().get("workItems", [])
            if work_items:
                return work_items[0]['id']  # Devuelve el ID del primer Feature encontrado
    except requests.exceptions.RequestException as e:
        st.error(f"Error de conexión al buscar Feature para {assigned_to}: {e}")
    return None # No se encontró o hubo un error

def check_story_exists(auth, organization, project, title, assigned_to, iteration_path, feature_id):
    """Usa WIQL para verificar si una User Story ya existe bajo un Feature padre específico."""
    wiql_url = f"https://dev.azure.com/{organization}/{project}/_apis/wit/wiql?api-version=7.1-preview.2"
    
    escaped_title = title.replace("'", "''")
    escaped_assigned_to = assigned_to.replace("'", "''")
    escaped_iteration_path = iteration_path.replace("\\", "\\\\")

    query = (
        "SELECT [System.Id] FROM WorkItems "
        f"WHERE [System.WorkItemType] = 'User Story' "
        f"AND [System.Title] = '{escaped_title}' "
        f"AND [System.AssignedTo] = '{escaped_assigned_to}' "
        f"AND [System.IterationPath] = '{escaped_iteration_path}' "
        f"AND [System.Parent] = {feature_id}"
    )
    
    wiql_body = {"query": query}
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(wiql_url, json=wiql_body, headers=headers, auth=auth)
        if response.status_code == 200 and len(response.json().get("workItems", [])) > 0:
            return True  # La HU ya existe
    except requests.exceptions.RequestException as e:
        st.error(f"Error de conexión al verificar HU para {assigned_to}: {e}")
    return False # No existe o no se pudo verificar

# ==== INPUTS ====
pat = st.text_input("PAT de Azure DevOps", type="password")
uploaded_file = st.file_uploader("Sube el archivo JSON de configuración de usuarios", type=["json"])

with st.expander("Ver formato del archivo JSON esperado (con vacaciones opcionales)"):
    st.code("""
[
  {
    "email": "devops.user@cleveritgroup.com", (Correo que aparece en Azure DevOps, es diferente al correo Clever)
    "profile": "DevOps",
    "description": "Descripción para el User Story. Ex: Asignación: Squad1 34%, Squad2 33%, Squad3 33%.",
    "vacaciones": "10, 11, 12" (Aqui vacaciones, Dias Libres o Beneficios, dejar vacio si no presenta ausencias programadas)
  },
  {
    "email": "sre.user@cleveritgroup.com", (Correo que aparece en Azure DevOps, es diferente al correo Clever)
    "profile": "SRE",
    "description": "Descripción para el User Story. Ex: Asignación: Squad1 34%, Squad2 33%, Squad3 33%.",
    "vacaciones":"" (Aqui vacaciones, Dias Libres o Beneficios, dejar vacio si no presenta ausencias programadas)
  },
  {
    "email": "security.user@cleveritgroup.com", (Correo que aparece en Azure DevOps, es diferente al correo Clever)
    "profile": "Seguridad",
    "description": "Descripción para el User Story. Ex: Asignación: Squad1 34%, Squad2 33%, Squad3 33%.",
    "vacaciones": "21, 22, 26, 28" (Aqui vacaciones, Dias Libres o Beneficios, dejar vacio si no presenta ausencias programadas)
  }
]
    """, language="json")

# ==== CÁLCULO DE FECHAS Y TÍTULOS DINÁMICOS ====
today = datetime.date.today()
start_date = today.replace(day=1)
_, last_day_num = calendar.monthrange(today.year, today.month)
end_date = today.replace(day=last_day_num)

meses = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}
nombre_mes = meses[today.month]
iteration_path = f"Servicios Staffing\\{nombre_mes} {today.year}"
feature_title_to_find = f"{nombre_mes} {today.year}"

# ==== CÁLCULO DE FERIADOS (PERÚ) ====
pe_holidays = {}
if holidays:
    pe_holidays = holidays.PE(years=today.year)
    # Filtrar feriados que caen dentro del mes actual y son días laborales
    holidays_in_month = {day: name for day, name in pe_holidays.items() if start_date <= day <= end_date and day.weekday() < 5}
    if holidays_in_month:
        st.info("Se omitirán los siguientes días feriados en Perú:")
        for day, name in sorted(holidays_in_month.items()):
            st.info(f"- **{day.strftime('%d/%m/%Y')}**: {name}")
else:
    st.warning("Librería 'holidays' no encontrada. No se omitirán feriados. Para activarlo, instala con: `pip install holidays`")

st.info(f"Se omitirán los días de vacaciones registrados en el **JSON**.")
st.info(f"Se crearán tareas para el mes actual: desde el **{start_date.strftime('%d/%m/%Y')}** hasta el **{end_date.strftime('%d/%m/%Y')}**.")
st.info(f"El Iteration Path detectado es: **{iteration_path}**")
st.info(f"Se buscará automáticamente el Feature ID para cada usuario con el título: **'{feature_title_to_find}'**.")

# ==== BOTÓN PRINCIPAL ====
if st.button("🚀 Crear User Stories"):
    if not pat or not uploaded_file:
        st.error("Debes ingresar un PAT y subir un archivo JSON.")
    else:
        try:
            stringio = io.StringIO(uploaded_file.getvalue().decode("utf-8"))
            user_data_list = json.load(stringio)
            if not isinstance(user_data_list, list) or not all(isinstance(i, dict) for i in user_data_list):
                st.error("El JSON debe ser una lista de objetos (una lista que empieza con `[`).")
                st.stop()
        except json.JSONDecodeError:
            st.error("Error al decodificar el archivo JSON. Revisa su formato.")
            st.stop()
        except Exception as e:
            st.error(f"Error al leer el archivo: {e}")
            st.stop()

        auth = HTTPBasicAuth('', pat)
        headers_creation = {"Content-Type": "application/json-patch+json"}

        work_days = sum(1 for i in range((end_date - start_date).days + 1) if (start_date + timedelta(days=i)).weekday() < 5)
        total_stories = len(user_data_list) * work_days
        progress_bar = st.progress(0)
        count = 0

        with st.spinner("Procesando usuarios y creando User Stories..."):
            for user_data in user_data_list:
                assigned_to = user_data.get("email")
                profile = user_data.get("profile")
                description = user_data.get("description", "")
                vacation_days_str = user_data.get("vacaciones", "")

                if not all([assigned_to, profile]):
                    st.warning(f"Saltando entrada inválida en JSON (faltan email o profile): {user_data}")
                    if total_stories > 0: total_stories -= work_days
                    continue
                
                #--- Parsear días de vacaciones ---
                vacation_days = set()
                if vacation_days_str:
                    try:
                        vacation_days = {int(day.strip()) for day in vacation_days_str.split(',')}
                    except (ValueError, AttributeError):
                        st.warning(f"⚠️ Formato de vacaciones inválido para {assigned_to}: '{vacation_days_str}'. Se ignorarán las vacaciones.")
                        vacation_days = set()

                # --- BÚSQUEDA AUTOMÁTICA DE FEATURE ID ---
                feature_id = find_feature_for_user(auth, organization, project, assigned_to, feature_title_to_find)
                
                if feature_id is None:
                    st.error(f"❌ No se encontró un Feature para **{assigned_to}** con el título '{feature_title_to_find}'. Saltando a este usuario.")
                    if total_stories > 0: total_stories -= work_days
                    continue
                
                st.write(f"--- Procesando para: **{assigned_to}** (Feature ID encontrado: {feature_id}) ---")

                if profile.lower() == 'devops':
                    title_prefix = "[Soporte DevOps]"
                elif profile.lower() == 'seguridad':
                    title_prefix = "[Ciberseguridad]"
                elif profile.lower() == 'SRE':
                    title_prefix = "[SRE]"
                else:
                    title_prefix = f"[{profile}]"

                current = start_date
                while current <= end_date:
                    if current.weekday() < 5:
                        # --- VERIFICACIÓN DE FERIADOS ---
                        if holidays and current in pe_holidays:
                            st.info(f"🎉 Omitiendo día feriado {current.strftime('%d/%m/%Y')} ({pe_holidays.get(current)})")
                            count += 1
                            if total_stories > 0:
                                progress_bar.progress(count / total_stories)
                            current += timedelta(days=1)
                            continue

                        # --- VERIFICACIÓN DE VACACIONES ---
                        if current.day in vacation_days:
                            st.info(f"🗓️ Omitiendo día de vacaciones {current.strftime('%d/%m/%Y')} para **{assigned_to}**.")
                            count += 1
                            if total_stories > 0:
                                progress_bar.progress(count / total_stories)
                            current += timedelta(days=1)
                            continue

                        title = f"{title_prefix} {current.day:02d}/{current.month:02d}/{current.year}"
                        
                        # --- VERIFICACIÓN MEJORADA (INCLUYE FEATURE ID) ---
                        if check_story_exists(auth, organization, project, title, assigned_to, iteration_path, feature_id):
                            st.warning(f"⏭️ Omitiendo '{title}' para **{assigned_to}**. Ya existe bajo el Feature {feature_id}.")
                        else:
                            start_datetime = datetime.datetime.combine(current, datetime.time(9, 0, tzinfo=local_tz))
                            end_datetime = datetime.datetime.combine(current, datetime.time(18, 0, tzinfo=local_tz))

                            url = f"https://dev.azure.com/{organization}/{project}/_apis/wit/workitems/$User%20Story?api-version=7.1-preview.3"

                            body = [
                                {"op": "add", "path": "/fields/System.Title", "value": title},
                                {"op": "add", "path": "/fields/System.AssignedTo", "value": assigned_to},
                                {"op": "add", "path": "/fields/Microsoft.VSTS.Scheduling.StartDate", "value": start_datetime.isoformat()},
                                {"op": "add", "path": "/fields/Microsoft.VSTS.Scheduling.TargetDate", "value": end_datetime.isoformat()},
                                {"op": "add", "path": "/fields/System.Description", "value": description},
                                {"op": "add", "path": "/fields/Microsoft.VSTS.Scheduling.CompletedWork", "value": 8},
                                {"op": "add", "path": "/fields/System.State", "value": "Closed"},
                                {"op": "add", "path": "/fields/System.AreaPath", "value": "Servicios Staffing\\Seguros Pacifico"},
                                {"op": "add", "path": "/fields/System.IterationPath", "value": iteration_path},
                                {
                                    "op": "add",
                                    "path": "/relations/-",
                                    "value": {
                                        "rel": "System.LinkTypes.Hierarchy-Reverse",
                                        "url": f"https://dev.azure.com/{organization}/{project}/_apis/wit/workItems/{feature_id}",
                                    },
                                },
                            ]

                            try:
                                response = requests.post(url, json=body, headers=headers_creation, auth=auth)
                                if response.status_code in [200, 201]:
                                    st.success(f"✅ Creada '{title}' para **{assigned_to}**")
                                else:
                                    st.error(f"❌ Error para **{assigned_to}** en '{title}': {response.status_code} — {response.text}")
                            except requests.exceptions.RequestException as e:
                                st.error(f"❌ Error de conexión para **{assigned_to}**: {e}")

                        count += 1
                        if total_stories > 0:
                            progress_bar.progress(count / total_stories)

                    current += timedelta(days=1)

        st.success("✅ Proceso finalizado.")
