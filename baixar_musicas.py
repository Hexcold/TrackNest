import os
import re
import json
import sys
import time
import base64
import shutil
import subprocess
import urllib.parse
import urllib.request
from threading import Lock
from urllib.parse import urlparse, parse_qs, urlunparse
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# CONFIGURAÇÕES PADRÃO
# ============================================================
CONFIG_PADRAO = {
    "downloads_simultaneos": 3,
    "qualidade_audio": "0",          # 0 = melhor qualidade
    "max_tentativas": 3,
    "pasta_raiz": "Musicas",
    "arquivo_lista": "musicas.json",
    "pular_se_existir": True,
    "usar_archive": True,
    "timeout_segundos": 600,
    "embed_thumbnail": True,

    # Cookies ajudam em sites que exigem sessão/login.
    # Exemplos: "chrome", "firefox", "edge", "brave", "chromium"
    "cookies_from_browser": None,
    "cookies_file": None,

    # Tenta expandir links curtos como vt.tiktok.com e links share do Facebook.
    "expandir_urls_curtas": True,

    # Spotify é usado apenas para ler metadados.
    "spotify_client_id": None,
    "spotify_client_secret": None,
    "spotify_market": "BR"
}

ARQUIVO_CONFIG = "config.json"
ARQUIVO_RELATORIO_JSON = "relatorio_falhas.json"
ARQUIVO_RELATORIO_TXT = "relatorio_falhas.txt"
ARQUIVO_ARCHIVE = "baixados_archive.txt"
ARQUIVO_MAPA_NOMES = "nomes_arquivos.json"

mapa_nomes = {}

print_lock = Lock()
nome_lock = Lock()
archive_lock = Lock()

RE_JA_NO_ARCHIVE = re.compile(
    r"\[download\]\s+([^\s:]+):\s+has already been recorded in the archive"
)


# ============================================================
# LOG SEGURO PARA THREADS
# ============================================================
def log(msg):
    with print_lock:
        print(msg, flush=True)


# ============================================================
# CONFIGURAÇÃO
# ============================================================
def carregar_config():
    config = CONFIG_PADRAO.copy()

    if not os.path.exists(ARQUIVO_CONFIG):
        return config

    try:
        with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
            dados = json.load(f)

        if isinstance(dados, dict):
            config.update(dados)
        else:
            log(f"⚠️  {ARQUIVO_CONFIG} deve conter um objeto JSON. Usando configuração padrão.")

    except json.JSONDecodeError as e:
        log(f"⚠️  Erro ao ler {ARQUIVO_CONFIG}: {e}")
        log("⚠️  Usando configuração padrão.")

    return config


# ============================================================
# UTILITÁRIOS DE TEXTO
# ============================================================
def sanitizar_nome(nome):
    """
    Remove caracteres inválidos para nomes de arquivos/pastas.
    Funciona bem no Windows.
    """
    if not nome:
        return "sem_titulo"

    nome = str(nome)
    nome = re.sub(r'[\\/*?:"<>|]', "_", nome)
    nome = re.sub(r"\s+", " ", nome)
    nome = nome.strip().rstrip(".")

    if not nome:
        return "sem_titulo"

    if len(nome) > 180:
        nome = nome[:180].strip().rstrip(".")

    return nome


def normalizar_texto_simples(texto):
    """
    Normaliza texto para detectar placeholders.
    Exemplo:
    "[NOME DA MUSICA]" vira "nome da musica".
    """
    if texto is None:
        return ""

    texto = str(texto).strip().lower()
    texto = texto.replace("[", "").replace("]", "")
    texto = texto.replace("_", " ").replace("-", " ")
    texto = re.sub(r"\s+", " ", texto)

    mapa = str.maketrans(
        "áàãâéêíóôõúç",
        "aaaaeeiooouc"
    )
    texto = texto.translate(mapa)

    return texto.strip()


def valor_vazio_ou_placeholder(valor):
    """
    Retorna True se o campo deve ser ignorado.
    Exemplo:
    None, "", "[NOME DO AUTOR]", "[NOME DA MUSICA]".
    """
    texto = normalizar_texto_simples(valor)

    if not texto:
        return True

    placeholders = {
        "null",
        "none",
        "sem titulo",
        "sem autor",
        "desconhecido",
        "nome do autor",
        "nome da musica",
        "nome da música",
        "nome do artista",
        "nome do video",
        "nome do vídeo",
        "autor",
        "artista",
        "titulo",
        "título"
    }

    return texto in placeholders


def obter_valor_real(valor):
    """
    Se for placeholder, retorna None.
    Se for valor real, retorna o texto limpo.
    """
    if valor_vazio_ou_placeholder(valor):
        return None

    return str(valor).strip()


# ============================================================
# URLS E PLATAFORMAS
# ============================================================
def detectar_plataforma(url):
    dominio = urlparse(url or "").netloc.lower()

    if "youtube.com" in dominio or "youtu.be" in dominio:
        return "youtube"

    if "spotify.com" in dominio:
        return "spotify"

    if "facebook.com" in dominio or "fb.watch" in dominio:
        return "facebook"

    if "tiktok.com" in dominio:
        return "tiktok"

    if "instagram.com" in dominio:
        return "instagram"

    if "kwai.com" in dominio or "kw.ai" in dominio or "kwai-video.com" in dominio:
        return "kwai"

    return "generico"


def normalizar_plataforma_item(item):
    """
    Usa a plataforma escrita no JSON, se existir.
    Caso esteja ausente ou estranha, tenta detectar pela URL.
    """
    url = item.get("url", "")
    plataforma = item.get("plataforma")

    if plataforma:
        p = str(plataforma).strip().lower()

        if p in {"youtube", "yt", "youtu.be", "youtube.com"}:
            return "youtube"

        if p in {"spotify", "spot"}:
            return "spotify"

        if p in {"facebook", "fb", "fb.watch"}:
            return "facebook"

        if p in {"tiktok", "tik tok", "vt.tiktok"}:
            return "tiktok"

        if p in {"instagram", "insta", "reel", "reels"}:
            return "instagram"

        if p in {"kwai", "kw.ai", "kwai-video"}:
            return "kwai"

        if p in {"generico", "generic", "outros", "outro"}:
            return "generico"

    return detectar_plataforma(url)


def normalizar_url_para_deduplicar(url):
    """
    Remove parâmetros desnecessários para evitar baixar o mesmo item duas vezes.
    """
    if not url:
        return ""

    url = url.strip()
    parsed = urlparse(url)
    dominio = parsed.netloc.lower()
    plataforma = detectar_plataforma(url)

    if "youtu.be" in dominio:
        video_id = parsed.path.strip("/").split("/")[0]
        return f"https://youtu.be/{video_id}"

    if "youtube.com" in dominio:
        query = parse_qs(parsed.query)
        video_id = query.get("v", [None])[0]
        playlist_id = query.get("list", [None])[0]

        if playlist_id and not video_id:
            return f"https://www.youtube.com/playlist?list={playlist_id}"

        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"

    if plataforma in {"spotify", "tiktok", "instagram", "kwai", "facebook"}:
        parsed_limpo = parsed._replace(query="", fragment="")
        return urlunparse(parsed_limpo).rstrip("/")

    parsed_limpo = parsed._replace(fragment="")
    return urlunparse(parsed_limpo).rstrip("/")


def deve_tentar_expandir_url(url):
    dominio = urlparse(url or "").netloc.lower()
    caminho = urlparse(url or "").path.lower()

    if "vt.tiktok.com" in dominio or "vm.tiktok.com" in dominio:
        return True

    if "fb.watch" in dominio:
        return True

    if "facebook.com" in dominio and "/share/" in caminho:
        return True

    return False


def expandir_url_curta(url):
    """
    Tenta seguir redirecionamentos de links curtos.
    Se falhar, devolve a URL original.
    """
    if not url:
        return url

    try:
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                )
            }
        )

        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)

        with opener.open(req, timeout=20) as resp:
            url_final = resp.geturl()

        if url_final and url_final != url:
            return url_final

    except Exception:
        pass

    return url


# ============================================================
# ARQUIVOS
# ============================================================
def carregar_lista(arquivo):
    try:
        with open(arquivo, "r", encoding="utf-8") as f:
            dados = json.load(f)

        if not isinstance(dados, list):
            log(f"❌ O arquivo {arquivo} deve conter uma lista JSON.")
            sys.exit(1)

        return dados

    except FileNotFoundError:
        log(f"❌ Arquivo {arquivo} não encontrado.")
        log("Crie um arquivo musicas.json no mesmo diretório do script.")
        sys.exit(1)

    except json.JSONDecodeError as e:
        log(f"❌ Erro no JSON {arquivo}: {e}")
        sys.exit(1)


def remover_duplicadas(itens):
    itens_unicos = []
    urls_vistas = set()

    for item in itens:
        if not isinstance(item, dict):
            log(f"⚠️  Item ignorado porque não é objeto JSON: {item}")
            continue

        url = item.get("url")

        if not url:
            log("⚠️  Item sem URL ignorado.")
            continue

        chave = normalizar_url_para_deduplicar(url)

        if chave in urls_vistas:
            log(f"⚠️  URL duplicada ignorada: {url}")
            continue

        item_limpo = item.copy()
        item_limpo["url"] = url.strip()
        itens_unicos.append(item_limpo)
        urls_vistas.add(chave)

    return itens_unicos


def carregar_mapa_nomes():
    global mapa_nomes

    if not os.path.exists(ARQUIVO_MAPA_NOMES):
        mapa_nomes = {}
        return

    try:
        with open(ARQUIVO_MAPA_NOMES, "r", encoding="utf-8") as f:
            mapa_nomes = json.load(f)
    except (json.JSONDecodeError, OSError):
        mapa_nomes = {}


def salvar_mapa_nomes():
    with open(ARQUIVO_MAPA_NOMES, "w", encoding="utf-8") as f:
        json.dump(mapa_nomes, f, ensure_ascii=False, indent=2)


def reservar_caminho_unico(caminho_mp3, url_normalizada):
    """
    Evita que vídeos de origens diferentes acabem com o mesmo nome de
    arquivo (ex: mesmo autor + título genérico "som original" do TikTok).

    Se o caminho já pertence a outra URL, adiciona um sufixo " (2)",
    " (3)"... A reserva é persistida em nomes_arquivos.json, então vale
    também entre execuções, não só dentro da mesma rodada.
    """
    pasta, nome_completo = os.path.split(caminho_mp3)
    nome, ext = os.path.splitext(nome_completo)

    with nome_lock:
        candidato = caminho_mp3
        contador = 2

        while True:
            dono = mapa_nomes.get(candidato)

            if dono is None or dono == url_normalizada:
                mapa_nomes[candidato] = url_normalizada
                salvar_mapa_nomes()
                return candidato

            candidato = os.path.join(pasta, f"{nome} ({contador}){ext}")
            contador += 1


def remover_id_do_archive(video_id):
    """
    Remove um ID do arquivo de archive do yt-dlp.

    Usado quando o yt-dlp reporta "has already been recorded in the
    archive" (retorna sucesso, sem baixar nada) mas o .mp3 final não
    existe no disco: o item ficou marcado como baixado numa execução
    anterior que não chegou a gerar o arquivo (ex: pós-processamento
    interrompido). Sem remover a marca, o item ficaria "com sucesso"
    para sempre sem nunca ser baixado de verdade.
    """
    if not video_id or not os.path.exists(ARQUIVO_ARCHIVE):
        return False

    with archive_lock:
        with open(ARQUIVO_ARCHIVE, "r", encoding="utf-8") as f:
            linhas = f.readlines()

        linhas_mantidas = [
            linha for linha in linhas
            if linha.strip().split(" ")[-1] != video_id
        ]

        if len(linhas_mantidas) == len(linhas):
            return False

        with open(ARQUIVO_ARCHIVE, "w", encoding="utf-8") as f:
            f.writelines(linhas_mantidas)

        return True


# ============================================================
# FERRAMENTAS
# ============================================================
def verificar_ferramentas_basicas():
    if not shutil.which("yt-dlp"):
        log("❌ yt-dlp não encontrado.")
        log("Instale ou atualize com:")
        log("python -m pip install -U yt-dlp")
        sys.exit(1)

    if not shutil.which("ffmpeg"):
        log("❌ ffmpeg não encontrado.")
        log("Instale o ffmpeg e adicione ao PATH.")
        sys.exit(1)

    try:
        versao = subprocess.run(
            ["yt-dlp", "--version"],
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()

        log(f"✅ yt-dlp OK: {versao}")

    except Exception:
        log("✅ yt-dlp encontrado.")

    log("✅ ffmpeg OK\n")


# ============================================================
# EXECUÇÃO DE COMANDOS
# ============================================================
def executar_comando(comando, timeout_segundos):
    try:
        resultado = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            timeout=timeout_segundos
        )

        return {
            "ok": resultado.returncode == 0,
            "returncode": resultado.returncode,
            "stdout": resultado.stdout or "",
            "stderr": resultado.stderr or "",
            "timeout": False
        }

    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "returncode": None,
            "stdout": e.stdout or "",
            "stderr": e.stderr or f"Timeout após {timeout_segundos} segundos.",
            "timeout": True
        }

    except Exception as e:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": str(e),
            "timeout": False
        }


def resumir_erro(stderr, limite=1200):
    if not stderr:
        return "Erro desconhecido."

    linhas = [linha.strip() for linha in stderr.splitlines() if linha.strip()]

    importantes = [
        linha for linha in linhas
        if "ERROR:" in linha
        or "WARNING:" in linha
        or "Unsupported URL" in linha
        or "HTTP Error" in linha
        or "Unable to extract" in linha
        or "Sign in" in linha
        or "login" in linha.lower()
        or "private" in linha.lower()
        or "cookie" in linha.lower()
        or "ffmpeg" in linha.lower()
        or "thumbnail" in linha.lower()
    ]

    texto = "\n".join(importantes[-10:] if importantes else linhas[-10:])

    if len(texto) > limite:
        texto = texto[:limite].rstrip() + "..."

    return texto


def classificar_erro(stderr, plataforma=None, timeout=False):
    erro = (stderr or "").lower()

    if timeout:
        return "timeout"

    if "arquivo final não foi gerado" in erro:
        return "arquivo_nao_gerado_apesar_de_sucesso_relatado"

    if "unsupported url" in erro:
        if plataforma == "kwai":
            return "kwai_sem_extrator_oficial_ou_url_incompativel"
        return "url_nao_suportada"

    if "private" in erro or "login" in erro or "sign in" in erro or "cookies" in erro or "cookie" in erro:
        return "precisa_de_login_ou_cookies"

    if "http error 403" in erro or "forbidden" in erro:
        return "bloqueio_403_ou_cookies"

    if "http error 404" in erro or "not found" in erro:
        return "video_nao_encontrado"

    if "not available" in erro or "unavailable" in erro:
        return "video_indisponivel"

    if "unable to extract" in erro:
        return "extrator_quebrado_ou_site_mudou"

    if "requested format is not available" in erro or "no video formats" in erro:
        return "formato_indisponivel"

    if "ffmpeg" in erro or "postprocess" in erro or "post-process" in erro:
        return "falha_no_ffmpeg_ou_pos_processamento"

    if "thumbnail" in erro:
        return "falha_ao_embutir_thumbnail"

    return "erro_desconhecido"


# ============================================================
# ADAPTADOR BASE
# ============================================================
class AdaptadorBase:
    nome = "base"

    def __init__(self, config):
        self.config = config

    def aceita(self, item):
        raise NotImplementedError

    def processar(self, item, indice, total):
        raise NotImplementedError


# ============================================================
# ADAPTADOR BASE PARA YT-DLP
# ============================================================
class AdaptadorYtdlpBase(AdaptadorBase):
    def opcoes_cookies(self):
        opcoes = []

        cookies_from_browser = self.config.get("cookies_from_browser")
        cookies_file = self.config.get("cookies_file")

        if cookies_from_browser:
            opcoes.extend(["--cookies-from-browser", str(cookies_from_browser)])

        elif cookies_file:
            opcoes.extend(["--cookies", str(cookies_file)])

        return opcoes

    def preparar_url(self, url):
        if not url:
            return url

        if self.config.get("expandir_urls_curtas") and deve_tentar_expandir_url(url):
            url_expandida = expandir_url_curta(url)

            if url_expandida != url:
                log(f"🔗 URL expandida:")
                log(f"   De:   {url}")
                log(f"   Para: {url_expandida}")

            return url_expandida

        return url

    def obter_metadados_ytdlp(self, url, playlist=False):
        """
        Busca metadados antes de baixar.
        Isso permite usar o título real do vídeo no nome do arquivo.
        """
        comando = [
            "yt-dlp",
            "--dump-single-json",
            "--skip-download",
            "--no-warnings"
        ]

        if playlist:
            comando.append("--yes-playlist")
        else:
            comando.append("--no-playlist")

        comando.extend(self.opcoes_cookies())
        comando.append(url)

        resultado = executar_comando(
            comando,
            timeout_segundos=int(self.config["timeout_segundos"])
        )

        if not resultado["ok"]:
            return None

        try:
            return json.loads(resultado["stdout"])
        except json.JSONDecodeError:
            return None

    def resolver_autor_titulo(self, item, plataforma, playlist=False):
        """
        Decide autor/título final.

        Prioridade:
        1. autor/título reais do JSON
        2. metadados do yt-dlp
        3. fallback usando somente template do yt-dlp
        """
        url = item.get("url")

        autor = obter_valor_real(item.get("autor"))
        titulo = obter_valor_real(item.get("titulo"))

        metadados = None

        if not playlist and (not autor or not titulo):
            metadados = self.obter_metadados_ytdlp(url, playlist=False)

        if metadados:
            if not titulo:
                titulo = (
                    metadados.get("track")
                    or metadados.get("title")
                    or metadados.get("fulltitle")
                    or metadados.get("alt_title")
                )

            if not autor:
                autor = (
                    metadados.get("artist")
                    or metadados.get("creator")
                    or metadados.get("uploader")
                    or metadados.get("channel")
                )

        autor = obter_valor_real(autor)
        titulo = obter_valor_real(titulo)

        return autor, titulo

    def montar_comando_download(
        self,
        url,
        nome_saida,
        playlist=False,
        usar_thumbnail=True,
        formato="bestaudio/best"
    ):
        comando = [
            "yt-dlp",
            "-f", formato,
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", str(self.config["qualidade_audio"]),
            "--add-metadata",
            "--retries", "10",
            "--fragment-retries", "10",
            "--socket-timeout", "30",
            # Força novo download em cada tentativa. As várias "estrategias"
            # de fallback usam o mesmo nome_saida; sem isso, o yt-dlp via
            # --continue/--no-overwrites reaproveitava um arquivo bruto
            # deixado por uma tentativa anterior (às vezes sem trilha de
            # áudio) em vez de baixar de novo, causando falha permanente em
            # "unable to obtain file audio codec with ffprobe".
            "--force-overwrites",
            "-o", nome_saida
        ]

        if playlist:
            comando.append("--yes-playlist")
            comando.append("--ignore-errors")
        else:
            comando.append("--no-playlist")

        if usar_thumbnail:
            comando.append("--embed-thumbnail")

        if self.config.get("usar_archive"):
            comando.extend(["--download-archive", ARQUIVO_ARCHIVE])

        comando.extend(self.opcoes_cookies())
        comando.append(url)

        return comando

    def baixar_com_ytdlp(self, item, indice, total, plataforma, playlist=False):
        url_original = item.get("url")

        if not url_original:
            return {
                "ok": False,
                "indice": indice,
                "plataforma": plataforma,
                "categoria": "url_vazia",
                "erro": "URL vazia."
            }

        url_preparada = self.preparar_url(url_original)

        item_para_metadados = item.copy()
        item_para_metadados["url"] = url_preparada

        autor, titulo = self.resolver_autor_titulo(
            item_para_metadados,
            plataforma,
            playlist=playlist
        )

        pasta_raiz = self.config["pasta_raiz"]

        if playlist:
            pasta_base = os.path.join(pasta_raiz, "YouTube")
            os.makedirs(pasta_base, exist_ok=True)

            nome_saida = os.path.join(
                pasta_base,
                "%(playlist_title).180B",
                "%(playlist_index)03d - %(title).180B.%(ext)s"
            )

            descricao = f"playlist: {url_preparada}"

        else:
            arquivo_mp3 = None
            url_normalizada = normalizar_url_para_deduplicar(url_original)

            # Caso 1: tem autor e título
            if autor and titulo:
                autor_limpo = sanitizar_nome(autor)
                titulo_limpo = sanitizar_nome(titulo)

                pasta_destino = os.path.join(pasta_raiz, autor_limpo)
                os.makedirs(pasta_destino, exist_ok=True)

                nome_base = sanitizar_nome(f"{autor_limpo} - {titulo_limpo}")
                arquivo_mp3 = os.path.join(pasta_destino, f"{nome_base}.mp3")
                arquivo_mp3 = reservar_caminho_unico(arquivo_mp3, url_normalizada)
                nome_saida = os.path.splitext(arquivo_mp3)[0] + ".%(ext)s"
                descricao = f"{autor} - {titulo}"

            # Caso 2: tem somente título
            elif titulo:
                titulo_limpo = sanitizar_nome(titulo)

                pasta_destino = os.path.join(
                    pasta_raiz,
                    plataforma.capitalize(),
                    "Desconhecidas"
                )
                os.makedirs(pasta_destino, exist_ok=True)

                nome_base = titulo_limpo
                arquivo_mp3 = os.path.join(pasta_destino, f"{nome_base}.mp3")
                arquivo_mp3 = reservar_caminho_unico(arquivo_mp3, url_normalizada)
                nome_saida = os.path.splitext(arquivo_mp3)[0] + ".%(ext)s"
                descricao = titulo

            # Caso 3: tem somente autor
            elif autor:
                autor_limpo = sanitizar_nome(autor)

                pasta_destino = os.path.join(pasta_raiz, autor_limpo)
                os.makedirs(pasta_destino, exist_ok=True)

                nome_saida = os.path.join(pasta_destino, "%(title).180B.%(ext)s")
                descricao = autor

            # Caso 4: não tem nem autor nem título
            else:
                pasta_destino = os.path.join(
                    pasta_raiz,
                    plataforma.capitalize(),
                    "Desconhecidas"
                )
                os.makedirs(pasta_destino, exist_ok=True)

                nome_saida = os.path.join(pasta_destino, "%(title).180B.%(ext)s")
                descricao = url_preparada

            if self.config.get("pular_se_existir") and arquivo_mp3 and os.path.exists(arquivo_mp3):
                log(f"⏭️  [{indice}/{total}] Já existe: {arquivo_mp3}")
                return {
                    "ok": True,
                    "indice": indice,
                    "plataforma": plataforma,
                    "url": url_original,
                    "arquivo": arquivo_mp3,
                    "pulou": True
                }

        estrategias = [
            {
                "nome": "audio_com_thumbnail",
                "formato": "bestaudio/best",
                "thumbnail": bool(self.config.get("embed_thumbnail"))
            },
            {
                "nome": "audio_sem_thumbnail",
                "formato": "bestaudio/best",
                "thumbnail": False
            },
            {
                "nome": "best_sem_thumbnail",
                "formato": "best",
                "thumbnail": False
            },
            {
                # Alguns vídeos do TikTok não têm trilha de áudio nos formatos
                # "limpos" (sem marca d'água), mesmo o yt-dlp listando
                # "acodec: aac" para eles. O formato "download" (com marca
                # d'água) é o único que garante áudio nesses casos.
                "nome": "download_com_audio_sem_thumbnail",
                "formato": "download/best",
                "thumbnail": False
            }
        ]

        ultimo_erro = None
        max_tentativas = int(self.config["max_tentativas"])

        for tentativa in range(1, max_tentativas + 1):
            for estrategia in estrategias:
                log(
                    f"🎵 [{indice}/{total}] {plataforma} | "
                    f"tentativa {tentativa}/{max_tentativas} | "
                    f"{estrategia['nome']} | {descricao}"
                )

                comando = self.montar_comando_download(
                    url=url_preparada,
                    nome_saida=nome_saida,
                    playlist=playlist,
                    usar_thumbnail=estrategia["thumbnail"],
                    formato=estrategia["formato"]
                )

                resultado = executar_comando(
                    comando,
                    timeout_segundos=int(self.config["timeout_segundos"])
                )

                if resultado["ok"] and not playlist and arquivo_mp3 and not os.path.exists(arquivo_mp3):
                    # O yt-dlp retornou sucesso, mas o .mp3 final não existe.
                    # Caso mais comum: o ID já estava marcado no archive de
                    # uma execução anterior que não chegou a gerar o
                    # arquivo, então o yt-dlp só pulou o download. Remove a
                    # marca e força uma nova tentativa real antes de desistir.
                    saida_completa = resultado["stdout"] + "\n" + resultado["stderr"]
                    match_archive = RE_JA_NO_ARCHIVE.search(saida_completa)

                    if match_archive and remover_id_do_archive(match_archive.group(1)):
                        log(
                            f"♻️  [{indice}/{total}] Marcado como já baixado, "
                            f"mas o arquivo não existe. Removendo do archive "
                            f"e baixando de novo: {descricao}"
                        )
                        resultado = executar_comando(
                            comando,
                            timeout_segundos=int(self.config["timeout_segundos"])
                        )

                    if resultado["ok"] and not os.path.exists(arquivo_mp3):
                        resultado = {
                            "ok": False,
                            "returncode": resultado["returncode"],
                            "stdout": resultado["stdout"],
                            "stderr": (
                                resultado["stderr"]
                                or "yt-dlp reportou sucesso, mas o arquivo final não foi gerado."
                            ),
                            "timeout": False
                        }

                if resultado["ok"]:
                    log(f"✅ [{indice}/{total}] Concluído: {descricao}")
                    return {
                        "ok": True,
                        "indice": indice,
                        "plataforma": plataforma,
                        "url": url_original,
                        "url_usada": url_preparada,
                        "pulou": False
                    }

                categoria = classificar_erro(
                    resultado["stderr"],
                    plataforma=plataforma,
                    timeout=resultado["timeout"]
                )

                ultimo_erro = {
                    "ok": False,
                    "indice": indice,
                    "plataforma": plataforma,
                    "url": url_original,
                    "url_usada": url_preparada,
                    "categoria": categoria,
                    "estrategia": estrategia["nome"],
                    "erro": resumir_erro(resultado["stderr"])
                }

                log(f"⚠️  [{indice}/{total}] Falhou: {categoria}")

                # Erros definitivos: não adianta repetir muito.
                if categoria in {
                    "precisa_de_login_ou_cookies",
                    "bloqueio_403_ou_cookies",
                    "url_nao_suportada",
                    "kwai_sem_extrator_oficial_ou_url_incompativel",
                    "video_nao_encontrado",
                    "video_indisponivel"
                }:
                    return ultimo_erro

            if tentativa < max_tentativas:
                time.sleep(4)

        return ultimo_erro or {
            "ok": False,
            "indice": indice,
            "plataforma": plataforma,
            "url": url_original,
            "categoria": "erro_desconhecido",
            "erro": "Falha sem mensagem."
        }


# ============================================================
# YOUTUBE
# ============================================================
class AdaptadorYouTube(AdaptadorYtdlpBase):
    nome = "youtube"

    def aceita(self, item):
        plataforma = normalizar_plataforma_item(item)
        return plataforma == "youtube"

    def eh_playlist(self, item):
        tipo = str(item.get("tipo") or "").lower()

        if tipo == "playlist":
            return True

        if tipo == "video":
            return False

        url = item.get("url", "")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        if "list" in query:
            return True

        if "/playlist" in parsed.path:
            return True

        return False

    def processar(self, item, indice, total):
        playlist = self.eh_playlist(item)

        return self.baixar_com_ytdlp(
            item=item,
            indice=indice,
            total=total,
            plataforma="youtube",
            playlist=playlist
        )


# ============================================================
# TIKTOK / INSTAGRAM / KWAI / FACEBOOK / GENÉRICO
# ============================================================
class AdaptadorGenericoYtdlp(AdaptadorYtdlpBase):
    nome = "generico_ytdlp"

    plataformas = {
        "tiktok",
        "instagram",
        "kwai",
        "facebook",
        "generico"
    }

    def aceita(self, item):
        plataforma = normalizar_plataforma_item(item)
        return plataforma in self.plataformas

    def processar(self, item, indice, total):
        plataforma = normalizar_plataforma_item(item)

        return self.baixar_com_ytdlp(
            item=item,
            indice=indice,
            total=total,
            plataforma=plataforma,
            playlist=False
        )


# ============================================================
# SPOTIFY - SOMENTE METADADOS
# ============================================================
class AdaptadorSpotify(AdaptadorBase):
    nome = "spotify"

    def aceita(self, item):
        plataforma = normalizar_plataforma_item(item)
        return plataforma == "spotify"

    def extrair_tipo_e_id(self, url):
        """
        Suporta:
        - https://open.spotify.com/playlist/ID
        - https://open.spotify.com/track/ID
        - spotify:playlist:ID
        - spotify:track:ID
        """
        if url.startswith("spotify:"):
            partes = url.split(":")
            if len(partes) >= 3:
                return partes[1], partes[2]

        parsed = urlparse(url)
        partes = [p for p in parsed.path.split("/") if p]

        if len(partes) >= 2:
            return partes[0], partes[1]

        return None, None

    def obter_token(self):
        client_id = self.config.get("spotify_client_id")
        client_secret = self.config.get("spotify_client_secret")

        if not client_id or not client_secret:
            raise RuntimeError(
                "Credenciais do Spotify ausentes. "
                "Preencha spotify_client_id e spotify_client_secret no config.json."
            )

        credenciais = f"{client_id}:{client_secret}".encode("utf-8")
        auth = base64.b64encode(credenciais).decode("utf-8")

        dados = urllib.parse.urlencode({
            "grant_type": "client_credentials"
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://accounts.spotify.com/api/token",
            data=dados,
            method="POST",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            resposta = json.loads(body)

        token = resposta.get("access_token")

        if not token:
            raise RuntimeError("Spotify não retornou access_token.")

        return token

    def get_json(self, url, token):
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            }
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)

    def normalizar_track(self, track):
        if not track:
            return None

        nome = track.get("name")
        artistas = track.get("artists") or []
        artista_nome = ", ".join(
            [a.get("name", "") for a in artistas if a.get("name")]
        )

        album = track.get("album") or {}
        album_nome = album.get("name")

        spotify_url = None
        external_urls = track.get("external_urls") or {}

        if external_urls.get("spotify"):
            spotify_url = external_urls["spotify"]

        if not nome:
            return None

        return {
            "autor": artista_nome or "Desconhecido",
            "titulo": nome,
            "album": album_nome,
            "duracao_ms": track.get("duration_ms"),
            "spotify_id": track.get("id"),
            "spotify_url": spotify_url
        }

    def buscar_track(self, spotify_id, token):
        mercado = self.config.get("spotify_market") or "BR"

        url = (
            f"https://api.spotify.com/v1/tracks/{spotify_id}"
            f"?market={urllib.parse.quote(mercado)}"
        )

        dados = self.get_json(url, token)
        track = self.normalizar_track(dados)

        if not track:
            raise RuntimeError("Não foi possível ler a faixa do Spotify.")

        return [track], f"Spotify Track - {track['autor']} - {track['titulo']}"

    def buscar_playlist(self, playlist_id, token):
        mercado = self.config.get("spotify_market") or "BR"

        playlist_url = (
            f"https://api.spotify.com/v1/playlists/{playlist_id}"
            "?fields=name,owner(display_name),tracks(total)"
        )

        playlist_info = self.get_json(playlist_url, token)
        nome_playlist = playlist_info.get("name") or f"playlist_{playlist_id}"

        tracks = []
        offset = 0
        limit = 100

        while True:
            params = urllib.parse.urlencode({
                "market": mercado,
                "limit": limit,
                "offset": offset,
                "fields": (
                    "items(track(name,artists(name),album(name),"
                    "duration_ms,external_urls,id)),next,total"
                )
            })

            url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks?{params}"
            dados = self.get_json(url, token)

            for item in dados.get("items", []):
                track = self.normalizar_track(item.get("track"))

                if track:
                    tracks.append(track)

            if not dados.get("next"):
                break

            offset += limit

        return tracks, nome_playlist

    def salvar_metadados(self, tracks, nome_colecao):
        pasta_base = os.path.join(
            self.config["pasta_raiz"],
            "Spotify",
            sanitizar_nome(nome_colecao)
        )

        os.makedirs(pasta_base, exist_ok=True)

        caminho_json = os.path.join(pasta_base, "spotify_tracks.json")
        caminho_txt = os.path.join(pasta_base, "spotify_tracks.txt")
        caminho_para_preencher = os.path.join(
            pasta_base,
            "para_preencher_urls_autorizadas.json"
        )

        with open(caminho_json, "w", encoding="utf-8") as f:
            json.dump(tracks, f, ensure_ascii=False, indent=2)

        with open(caminho_txt, "w", encoding="utf-8") as f:
            for i, track in enumerate(tracks, start=1):
                f.write(f"{i:03d}. {track['autor']} - {track['titulo']}\n")

        modelo_urls = [
            {
                "plataforma": "youtube",
                "tipo": "video",
                "autor": track["autor"],
                "titulo": track["titulo"],
                "url": None,
                "origem_spotify_url": track.get("spotify_url")
            }
            for track in tracks
        ]

        with open(caminho_para_preencher, "w", encoding="utf-8") as f:
            json.dump(modelo_urls, f, ensure_ascii=False, indent=2)

        return {
            "json": caminho_json,
            "txt": caminho_txt,
            "modelo_urls": caminho_para_preencher
        }

    def processar(self, item, indice, total):
        url = item.get("url")

        if not url:
            return {
                "ok": False,
                "indice": indice,
                "plataforma": "spotify",
                "categoria": "url_vazia",
                "erro": "URL vazia."
            }

        try:
            tipo_real, spotify_id = self.extrair_tipo_e_id(url)

            if tipo_real not in {"playlist", "track"} or not spotify_id:
                return {
                    "ok": False,
                    "indice": indice,
                    "plataforma": "spotify",
                    "url": url,
                    "categoria": "spotify_tipo_nao_suportado",
                    "erro": "Use URL de playlist ou track do Spotify."
                }

            log(f"🎧 [{indice}/{total}] Spotify | lendo metadados de {tipo_real}: {url}")

            token = self.obter_token()

            if tipo_real == "playlist":
                tracks, nome_colecao = self.buscar_playlist(spotify_id, token)
            else:
                tracks, nome_colecao = self.buscar_track(spotify_id, token)

            arquivos = self.salvar_metadados(tracks, nome_colecao)

            log(f"✅ [{indice}/{total}] Spotify lido: {len(tracks)} faixa(s)")
            log(f"   📄 {arquivos['txt']}")

            return {
                "ok": True,
                "indice": indice,
                "plataforma": "spotify",
                "url": url,
                "tracks": len(tracks),
                "arquivos": arquivos
            }

        except Exception as e:
            return {
                "ok": False,
                "indice": indice,
                "plataforma": "spotify",
                "url": url,
                "categoria": "erro_spotify",
                "erro": str(e)
            }


# ============================================================
# GERENCIADOR DE ADAPTADORES
# ============================================================
def escolher_adaptador(item, adaptadores):
    for adaptador in adaptadores:
        if adaptador.aceita(item):
            return adaptador

    return None


def processar_item(item, indice, total, adaptadores):
    try:
        adaptador = escolher_adaptador(item, adaptadores)

        if not adaptador:
            return {
                "ok": False,
                "indice": indice,
                "url": item.get("url"),
                "categoria": "plataforma_nao_suportada",
                "erro": "Nenhum adaptador aceitou esse item."
            }

        return adaptador.processar(item, indice, total)

    except Exception as e:
        return {
            "ok": False,
            "indice": indice,
            "url": item.get("url"),
            "categoria": "erro_inesperado",
            "erro": str(e)
        }


# ============================================================
# RELATÓRIOS
# ============================================================
def salvar_relatorios(resultados):
    falhas = [r for r in resultados if not r.get("ok")]

    with open(ARQUIVO_RELATORIO_JSON, "w", encoding="utf-8") as f:
        json.dump(falhas, f, ensure_ascii=False, indent=2)

    with open(ARQUIVO_RELATORIO_TXT, "w", encoding="utf-8") as f:
        if not falhas:
            f.write("Nenhuma falha registrada.\n")
            return

        for falha in falhas:
            f.write("=" * 70 + "\n")
            f.write(f"Índice: {falha.get('indice')}\n")
            f.write(f"Plataforma: {falha.get('plataforma')}\n")
            f.write(f"URL original: {falha.get('url')}\n")
            f.write(f"URL usada: {falha.get('url_usada')}\n")
            f.write(f"Categoria: {falha.get('categoria')}\n")
            f.write(f"Estratégia: {falha.get('estrategia')}\n")
            f.write("Erro:\n")
            f.write(str(falha.get("erro")) + "\n\n")


def mostrar_dicas(resultados):
    falhas = [r for r in resultados if not r.get("ok")]

    if not falhas:
        return

    categorias = {}

    for falha in falhas:
        categoria = falha.get("categoria", "erro_desconhecido")
        categorias[categoria] = categorias.get(categoria, 0) + 1

    log("\n📌 Tipos de falha:")
    for categoria, qtd in sorted(categorias.items()):
        log(f"   - {categoria}: {qtd}")

    if any(
        f.get("categoria") in {
            "precisa_de_login_ou_cookies",
            "bloqueio_403_ou_cookies"
        }
        for f in falhas
    ):
        log("\n💡 Alguns links podem precisar de cookies.")
        log('   No config.json, teste: "cookies_from_browser": "chrome"')
        log('   ou: "cookies_from_browser": "firefox"')

    if any(f.get("plataforma") == "facebook" for f in falhas):
        log("\n💡 Facebook costuma falhar com link privado, restrito ou /share/v/.")
        log("   Tente abrir o vídeo no navegador, copiar a URL final e usar cookies do navegador.")

    if any(f.get("plataforma") == "kwai" for f in falhas):
        log("\n💡 Kwai nem sempre é suportado pelo yt-dlp.")
        log("   Alguns links funcionam e outros não, dependendo do formato do link.")

    if any(f.get("categoria") == "erro_spotify" for f in falhas):
        log("\n💡 Para Spotify, confira spotify_client_id e spotify_client_secret no config.json.")

    if any(f.get("categoria") == "extrator_quebrado_ou_site_mudou" for f in falhas):
        log("\n💡 Atualize o yt-dlp:")
        log("   python -m pip install -U yt-dlp")

    if any(f.get("categoria") == "arquivo_nao_gerado_apesar_de_sucesso_relatado" for f in falhas):
        log("\n💡 O yt-dlp reportou sucesso, mas o .mp3 não foi gerado mesmo após")
        log("   remover o item do archive e tentar de novo. Pode ser falha no")
        log("   pós-processamento (ffmpeg/thumbnail). Rode o script de novo.")


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================
def main():
    print("=" * 72)
    print("   🎵 BAIXADOR MODULAR - YouTube / Spotify / TikTok / Instagram / Kwai / Facebook")
    print("=" * 72)

    config = carregar_config()
    verificar_ferramentas_basicas()
    carregar_mapa_nomes()

    os.makedirs(config["pasta_raiz"], exist_ok=True)

    itens = carregar_lista(config["arquivo_lista"])
    itens = remover_duplicadas(itens)

    if not itens:
        log("❌ Nenhum item válido encontrado.")
        sys.exit(1)

    adaptadores = [
        AdaptadorYouTube(config),
        AdaptadorSpotify(config),
        AdaptadorGenericoYtdlp(config)
    ]

    total = len(itens)

    log(f"📋 Itens encontrados: {total}")
    log(f"⚡ Downloads simultâneos: {config['downloads_simultaneos']}")
    log(f"📁 Pasta raiz: {config['pasta_raiz']}")

    if config.get("cookies_from_browser"):
        log(f"🍪 Cookies do navegador: {config['cookies_from_browser']}")
    elif config.get("cookies_file"):
        log(f"🍪 Arquivo de cookies: {config['cookies_file']}")
    else:
        log("🍪 Cookies: desativado")

    log("")

    resultados = []

    with ThreadPoolExecutor(max_workers=int(config["downloads_simultaneos"])) as executor:
        futures = [
            executor.submit(processar_item, item, i, total, adaptadores)
            for i, item in enumerate(itens, start=1)
        ]

        for future in as_completed(futures):
            try:
                resultados.append(future.result())
            except Exception as e:
                resultados.append({
                    "ok": False,
                    "categoria": "erro_thread",
                    "erro": str(e)
                })

    sucessos = sum(1 for r in resultados if r.get("ok"))
    falhas = sum(1 for r in resultados if not r.get("ok"))
    pulados = sum(1 for r in resultados if r.get("pulou"))

    salvar_relatorios(resultados)

    print()
    print("=" * 72)
    print(f"✅ Sucessos: {sucessos}")
    print(f"⏭️  Pulados: {pulados}")
    print(f"❌ Falhas: {falhas}")
    print(f"📝 Relatório JSON: {ARQUIVO_RELATORIO_JSON}")
    print(f"📝 Relatório TXT: {ARQUIVO_RELATORIO_TXT}")
    print("=" * 72)

    mostrar_dicas(resultados)


if __name__ == "__main__":
    main()