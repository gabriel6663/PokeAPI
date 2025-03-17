from flask import Flask, redirect, url_for, session, request, jsonify, abort
from authlib.integrations.flask_client import OAuth
from flask_login import LoginManager, UserMixin, login_user, login_required
import logging
import requests
from functools import wraps
import random
import os
from dotenv import load_dotenv

# Carga de variables de entorno
load_dotenv()

# Configuracion de logging
logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    filemode='a'
)

# Lista de emails permitidos (obtenidos de las variables de entorno)
EMAILS_PERMITIDOS = os.getenv("EMAILS_PERMITIDOS", "").split(",")

# Inicializacion de la aplicacion Flask
app = Flask(__name__)
app.config.from_object("config")
app.secret_key = app.config["SECRET"]

# Registro de Auth0
oauth = OAuth(app)
auth0 = oauth.register(
    "auth0",
    client_id=app.config["AUTH0_CLIENT_ID"],
    client_secret=app.config["AUTH0_CLIENT_SECRET"],
    api_base_url=f"https://{app.config['AUTH0_DOMAIN']}",
    access_token_url=f"https://{app.config['AUTH0_DOMAIN']}/oauth/token",
    authorize_url=f"https://{app.config['AUTH0_DOMAIN']}/authorize",
    jwks_uri=f"https://{app.config['AUTH0_DOMAIN']}/.well-known/jwks.json",
    client_kwargs={
        "scope": "openid profile email",
        "authorization_endpoint": f"https://{app.config['AUTH0_DOMAIN']}/authorize",
        "token_endpoint": f"https://{app.config['AUTH0_DOMAIN']}/oauth/token",
    },
)

# Configuracion de Flask-Login
login_manager = LoginManager(app)

class User(UserMixin):
    def __init__(self, user_id, name, email):
        self.id = user_id
        self.name = name
        self.email = email

@login_manager.user_loader
def load_user(user_id):
    # Se carga el usuario de la sesion actual
    user_session = session.get("user")
    if user_session:
        logging.info(f"Cargando usuario: {user_session.get('email')}")
        return User(user_id, user_session["name"], user_session["email"])
    logging.warning("No se encontro informacion de usuario en la sesion")
    return None

@app.route("/")
def home():
    # Pagina principal con un enlace para iniciar sesion
    logging.info("Acceso a la pagina principal")
    return "Bienvenido a la PokeAPI debe iniciar sesion para continuar. <a href='/login'>Iniciar sesion</a>"

@app.route("/login")
def login():
    # Inicia el proceso de autenticacion redirigiendo a Auth0
    logging.info("Redirigiendo a Auth0 para el inicio de sesion")
    return auth0.authorize_redirect(redirect_uri=app.config["AUTH0_CALLBACK_URL"])

@app.route("/callback")
def callback():
    # Se recibe el callback de Auth0 luego de autenticarse
    logging.info("Callback recibido de Auth0")
    try:
        token = auth0.authorize_access_token()
        user_info = auth0.get("userinfo").json()
        session["user"] = user_info
        user = User(user_info["sub"], user_info["name"], user_info["email"])
        login_user(user)
        logging.info(f"Usuario autenticado: {user.email}")
        return redirect(url_for("dashboard"))
    except Exception as e:
        logging.exception("Error durante el callback de autenticacion")
        return jsonify({"error": "Error en el proceso de autenticacion"}), 500

@app.route("/dashboard")
@login_required
def dashboard():
    # Dashboard que muestra la informacion del usuario autenticado
    logging.info("Acceso al dashboard")
    return jsonify(session["user"])

@app.route("/logout")
def logout():
    # Finaliza la sesion y redirige al logout de Auth0
    logging.info("Cerrando sesion del usuario")
    session.clear()
    return redirect(
        f"https://{app.config['AUTH0_DOMAIN']}/v2/logout?client_id={app.config['AUTH0_CLIENT_ID']}&returnTo=http://localhost:5000"
    )

def requiere_autorizacion(f):
    """
    Funcion para asegurar que el usuario este autenticado y autorizado.
    Redirige a login si no se encuentra en la sesion y rechaza si el email no esta permitido.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session or "email" not in session["user"]:
            logging.warning("Acceso denegado: usuario no autenticado")
            return redirect(url_for("login"))
        if session["user"]["email"] not in EMAILS_PERMITIDOS:
            logging.warning(f"Acceso denegado para el email: {session['user']['email']}")
            return abort(403)  # No autorizado
        return f(*args, **kwargs)
    return decorated_function

@app.route('/pokemon/type', methods=['GET'])
@requiere_autorizacion
def get_pokemon_type():
    """
    Endpoint para obtener el tipo de un Pokemon dado su nombre.
    Se espera el parametro 'name'.
    """
    name = request.args.get('name')
    logging.info(f"Solicitud de tipos para Pokemon: {name}")
    if not name:
        logging.error("Falta el parametro 'name'")
        return jsonify({"error": "Falta el parametro 'name'"}), 400
    try:
        # Se realiza la solicitud a la API de Pokemon
        response = requests.get(f"{app.config['POKEAPI_BASE_URL']}/pokemon/{name.lower()}")
        if response.status_code != 200:
            logging.error(f"Pokemon {name} no encontrado (status code: {response.status_code})")
            return jsonify({"error": "Pokemon no encontrado"}), 404
        data = response.json()
        # Se extraen todos los tipos asociados al Pokemon
        types = [t['type']['name'] for t in data.get('types', [])]
        logging.info(f"Tipos encontrados para {name}: {types}")
        return jsonify({"name": name, "types": types})
    except Exception as e:
        logging.exception("Error al obtener el tipo de Pokemon")
        return jsonify({"error": "Error interno del servidor"}), 500

@app.route('/pokemon/random', methods=['GET'])
@requiere_autorizacion
def get_random_pokemon_by_type():
    """
    Endpoint para obtener un Pokemon al azar de un tipo especifico.
    Se espera el parametro 'type'.
    """
    pokemon_type = request.args.get('type')
    logging.info(f"Solicitud de Pokemon aleatorio para el tipo: {pokemon_type}")
    if not pokemon_type:
        logging.error("Falta el parametro 'type'")
        return jsonify({"error": "Falta el parametro 'type'"}), 400
    try:
        response = requests.get(f"{app.config['POKEAPI_BASE_URL']}/type/{pokemon_type.lower()}")
        if response.status_code != 200:
            logging.error(f"Tipo {pokemon_type} no encontrado (status code: {response.status_code})")
            return jsonify({"error": "Tipo no encontrado"}), 404
        data = response.json()
        # Se obtiene la lista de Pokemon asociados al tipo
        pokemons = [p['pokemon'] for p in data.get('pokemon', [])]
        if not pokemons:
            logging.error(f"No se encontraron Pokemon para el tipo {pokemon_type}")
            return jsonify({"error": "No se encontraron Pokemon para este tipo"}), 404
        random_pokemon = random.choice(pokemons)
        logging.info(f"Pokemon aleatorio seleccionado: {random_pokemon['name']}")
        return jsonify(random_pokemon)
    except Exception as e:
        logging.exception("Error al obtener un Pokemon al azar")
        return jsonify({"error": "Error interno del servidor"}), 500

@app.route('/pokemon/longest', methods=['GET'])
@requiere_autorizacion
def get_longest_name_pokemon():
    """
    Endpoint para obtener el Pokemon con el nombre mas largo
    de un tipo especifico. Se espera el parametro 'type' en la query string.
    """
    pokemon_type = request.args.get('type')
    logging.info(f"Solicitud de Pokemon con nombre mas largo para el tipo: {pokemon_type}")
    if not pokemon_type:
        logging.error("Falta el parametro 'type'")
        return jsonify({"error": "Falta el parametro 'type'"}), 400
    try:
        response = requests.get(f"{app.config['POKEAPI_BASE_URL']}/type/{pokemon_type.lower()}")
        if response.status_code != 200:
            logging.error(f"Tipo {pokemon_type} no encontrado (status code: {response.status_code})")
            return jsonify({"error": "Tipo no encontrado"}), 404
        data = response.json()
        pokemons = [p['pokemon'] for p in data.get('pokemon', [])]
        if not pokemons:
            logging.error(f"No se encontraron Pokemon para el tipo {pokemon_type}")
            return jsonify({"error": "No se encontraron Pokemon para este tipo"}), 404
        # Se selecciona el Pokemon cuyo nombre tenga mayor longitud
        longest_pokemon = max(pokemons, key=lambda x: len(x['name']))
        logging.info(f"Pokemon con nombre mas largo: {longest_pokemon['name']}")
        return jsonify(longest_pokemon)
    except Exception as e:
        logging.exception("Error al obtener el Pokemon con el nombre mas largo")
        return jsonify({"error": "Error interno del servidor"}), 500

if __name__ == "__main__":
    logging.info("Iniciando la aplicacion Flask en modo debug")
    app.run(debug=True)
