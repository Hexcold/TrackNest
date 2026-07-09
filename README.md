# 🎵 TrackNest

Ferramenta modular em Python para coletar, converter e organizar áudios a partir de links de diferentes plataformas, com suporte a YouTube, playlists do YouTube, TikTok, Instagram, Kwai, Facebook e leitura de metadados do Spotify.

> Projeto desenvolvido com auxílio de uma LLM (Large Language Model), usada para apoiar a estruturação do código, refatoração, tratamento de erros e documentação.

---

## 📌 Sobre o projeto

O **TrackNest** nasceu como um script simples para baixar músicas a partir de uma lista em JSON e evoluiu para uma ferramenta modular, separando o tratamento de cada plataforma.

A ideia principal é evitar que uma falha em uma plataforma quebre o funcionamento das demais. Por exemplo: se um link do Kwai ou Facebook falhar, o script continua processando YouTube, TikTok, Instagram e outros itens da lista.

O script usa principalmente o `yt-dlp` para extração e download de mídia, e o `ffmpeg` para conversão do áudio para MP3.

---

## ⚠️ Aviso de uso responsável

Este projeto deve ser usado apenas para conteúdos que você tem direito de baixar, como:

- conteúdos próprios;
- conteúdos livres de direitos autorais;
- conteúdos com permissão explícita de uso;
- mídias públicas quando o download for permitido pelos termos da plataforma.

O autor deste projeto não incentiva pirataria, violação de direitos autorais ou uso indevido de conteúdo protegido.

O suporte ao Spotify é apenas para leitura de metadados. O script não baixa áudio diretamente do Spotify.

---

## ✨ Funcionalidades

- Download de áudio em MP3.
- Suporte a vídeos individuais do YouTube.
- Suporte a playlists inteiras do YouTube.
- Suporte a links do TikTok.
- Suporte a links do Instagram.
- Suporte parcial a links do Kwai.
- Suporte parcial a links do Facebook.
- Leitura de metadados de playlists/faixas do Spotify.
- Organização automática por artista ou plataforma.
- Detecção de autor e título via metadados do `yt-dlp`.
- Ignora placeholders como `[NOME DO AUTOR]` e `[NOME DA MUSICA]`.
- Expansão de URLs curtas, como `vt.tiktok.com`.
- Tratamento de falhas por categoria.
- Relatório de falhas em `.json` e `.txt`.
- Controle de downloads já realizados com `baixados_archive.txt`.
- Suporte opcional a cookies do navegador.

---

## 📁 Estrutura do projeto

```text
tracknest/
├── baixar_musicas.py
├── musicas.json
├── config.json
├── Musicas/
├── baixados_archive.txt
├── nomes_arquivos.json
├── relatorio_falhas.json
└── relatorio_falhas.txt
```

### Arquivos principais

| Arquivo | Descrição |
|---|---|
| `baixar_musicas.py` | Script principal |
| `musicas.json` | Lista de links para processar |
| `config.json` | Configurações opcionais |
| `Musicas/` | Pasta onde os arquivos MP3 são salvos |
| `baixados_archive.txt` | Histórico usado para evitar baixar o mesmo item novamente |
| `nomes_arquivos.json` | Reserva de nomes de arquivo por URL, para não misturar vídeos diferentes com o mesmo nome (ex: "som original" do TikTok) |
| `relatorio_falhas.json` | Relatório detalhado das falhas |
| `relatorio_falhas.txt` | Relatório legível das falhas |

---

## ✅ Requisitos

Antes de usar, instale:

- Python 3.10 ou superior;
- `yt-dlp`;
- `ffmpeg`.

---

## 🐍 Instalação do yt-dlp

```bash
python -m pip install -U yt-dlp
```

Para verificar se instalou corretamente:

```bash
yt-dlp --version
```

---

## 🎧 Instalação do ffmpeg

### Windows

Baixe o `ffmpeg` em:

```text
https://ffmpeg.org/download.html
```

Depois, adicione a pasta `bin` do `ffmpeg` ao `PATH` do Windows.

Para testar:

```bash
ffmpeg -version
```

### Arch Linux

```bash
sudo pacman -S ffmpeg
```

### Ubuntu/Debian

```bash
sudo apt install ffmpeg
```

---

## ⚙️ Configuração

Crie um arquivo `config.json` na mesma pasta do script.

Exemplo:

```json
{
  "downloads_simultaneos": 3,
  "qualidade_audio": "0",
  "max_tentativas": 3,
  "pasta_raiz": "Musicas",
  "arquivo_lista": "musicas.json",
  "pular_se_existir": true,
  "usar_archive": true,
  "timeout_segundos": 600,
  "embed_thumbnail": true,

  "cookies_from_browser": null,
  "cookies_file": null,
  "expandir_urls_curtas": true,

  "spotify_client_id": null,
  "spotify_client_secret": null,
  "spotify_market": "BR"
}
```

---

## 🍪 Uso de cookies

Algumas plataformas podem exigir login ou sessão ativa, principalmente Facebook, Instagram e TikTok.

Nesses casos, você pode usar cookies do navegador.

Exemplo com Chrome:

```json
"cookies_from_browser": "chrome"
```

Exemplo com Firefox:

```json
"cookies_from_browser": "firefox"
```

O campo deve ficar dentro do `config.json`.

Exemplo completo:

```json
{
  "downloads_simultaneos": 3,
  "qualidade_audio": "0",
  "max_tentativas": 3,
  "pasta_raiz": "Musicas",
  "arquivo_lista": "musicas.json",
  "pular_se_existir": true,
  "usar_archive": true,
  "timeout_segundos": 600,
  "embed_thumbnail": true,

  "cookies_from_browser": "chrome",
  "cookies_file": null,
  "expandir_urls_curtas": true,

  "spotify_client_id": null,
  "spotify_client_secret": null,
  "spotify_market": "BR"
}
```

---

## 📝 Formato do `musicas.json`

O arquivo `musicas.json` deve conter uma lista de objetos.

Exemplo básico:

```json
[
  {
    "plataforma": "youtube",
    "tipo": "video",
    "autor": "Jorge Aureliano",
    "titulo": "A gente se ama",
    "url": "https://youtu.be/p1EMrMkvswk"
  },
  {
    "plataforma": "kwai",
    "tipo": "video",
    "autor": null,
    "titulo": null,
    "url": "https://kwai-video.com/p/RNACE5xb"
  },
  {
    "plataforma": "tiktok",
    "tipo": "video",
    "autor": null,
    "titulo": null,
    "url": "https://vt.tiktok.com/EXEMPLO/"
  }
]
```

Quando `autor` e `titulo` estiverem como `null`, o script tenta buscar essas informações automaticamente usando os metadados do `yt-dlp`.

Evite usar placeholders como:

```json
"autor": "[NOME DO AUTOR]",
"titulo": "[NOME DA MUSICA]"
```

Mesmo assim, o script já tenta ignorar esses valores automaticamente.

---

## ▶️ Como executar

No terminal, entre na pasta do projeto:

```bash
cd caminho/para/tracknest
```

Execute:

```bash
python baixar_musicas.py
```

No Windows, também pode ser:

```bash
py baixar_musicas.py
```

---

## 📦 Exemplo de saída

Os arquivos serão salvos na pasta `Musicas`.

Exemplo:

```text
Musicas/
├── Jorge Aureliano/
│   └── Jorge Aureliano - A gente se ama.mp3
├── Kwai/
│   └── Desconhecidas/
│       └── Nome real do vídeo.mp3
└── YouTube/
    └── Nome da Playlist/
        ├── 001 - Música 1.mp3
        ├── 002 - Música 2.mp3
        └── 003 - Música 3.mp3
```

---

## 📺 YouTube

### Vídeo individual

```json
{
  "plataforma": "youtube",
  "tipo": "video",
  "autor": "Artista",
  "titulo": "Nome da música",
  "url": "https://www.youtube.com/watch?v=ID_DO_VIDEO"
}
```

### Playlist

```json
{
  "plataforma": "youtube",
  "tipo": "playlist",
  "url": "https://www.youtube.com/playlist?list=ID_DA_PLAYLIST"
}
```

As playlists são salvas em:

```text
Musicas/YouTube/Nome da Playlist/
```

---

## 🎧 Spotify

O Spotify é usado apenas para leitura de metadados.

O script pode ler playlists e faixas do Spotify e gerar arquivos auxiliares com artista, título e link original.

Ele não baixa áudio diretamente do Spotify.

Para usar Spotify, preencha no `config.json`:

```json
{
  "spotify_client_id": "SEU_CLIENT_ID",
  "spotify_client_secret": "SEU_CLIENT_SECRET",
  "spotify_market": "BR"
}
```

Exemplo de item:

```json
{
  "plataforma": "spotify",
  "tipo": "playlist",
  "url": "https://open.spotify.com/playlist/ID_DA_PLAYLIST"
}
```

O resultado será salvo em:

```text
Musicas/Spotify/Nome da Playlist/
├── spotify_tracks.json
├── spotify_tracks.txt
└── para_preencher_urls_autorizadas.json
```

---

## 📱 TikTok, Instagram, Kwai e Facebook

Essas plataformas são tratadas por um adaptador genérico baseado no `yt-dlp`.

### TikTok

```json
{
  "plataforma": "tiktok",
  "tipo": "video",
  "autor": null,
  "titulo": null,
  "url": "https://vt.tiktok.com/EXEMPLO/"
}
```

### Instagram

```json
{
  "plataforma": "instagram",
  "tipo": "video",
  "autor": null,
  "titulo": null,
  "url": "https://www.instagram.com/reel/EXEMPLO/"
}
```

### Kwai

```json
{
  "plataforma": "kwai",
  "tipo": "video",
  "autor": null,
  "titulo": null,
  "url": "https://kwai-video.com/p/EXEMPLO"
}
```

### Facebook

```json
{
  "plataforma": "facebook",
  "tipo": "video",
  "autor": null,
  "titulo": null,
  "url": "https://www.facebook.com/share/v/EXEMPLO/"
}
```

Alguns links podem falhar por limitações da própria plataforma, necessidade de login, conteúdo privado, mudança no site ou falta de suporte completo no `yt-dlp`.

---

## 🧾 Relatórios de falha

Ao final da execução, o script gera:

```text
relatorio_falhas.json
relatorio_falhas.txt
```

Esses arquivos ajudam a identificar o motivo da falha.

Exemplos de categorias:

```text
url_nao_suportada
precisa_de_login_ou_cookies
bloqueio_403_ou_cookies
video_nao_encontrado
video_indisponivel
kwai_sem_extrator_oficial_ou_url_incompativel
falha_no_ffmpeg_ou_pos_processamento
arquivo_nao_gerado_apesar_de_sucesso_relatado
erro_desconhecido
```

---

## 🔁 Evitando downloads duplicados

O script usa o arquivo:

```text
baixados_archive.txt
```

Ele registra os itens já baixados para evitar repetir downloads.

Se o script detectar que um item consta como já baixado no
`baixados_archive.txt` mas o `.mp3` correspondente não existe na pasta
`Musicas/` (por exemplo, porque uma execução anterior foi interrompida
depois do download mas antes da conversão), ele remove esse item do
archive automaticamente e baixa de novo, em vez de reportar sucesso
sem gerar o arquivo.

Se quiser forçar tudo novamente, apague:

```bash
rm -f baixados_archive.txt
```

No Windows:

```bat
del baixados_archive.txt
```

Também é possível apagar a pasta de músicas:

```bat
rmdir /s /q Musicas
```

---

## 🧹 Limpando testes antigos

No Windows:

```bat
rmdir /s /q Musicas
del baixados_archive.txt
del nomes_arquivos.json
del relatorio_falhas.json
del relatorio_falhas.txt
```

No Linux/macOS:

```bash
rm -rf Musicas
rm -f baixados_archive.txt nomes_arquivos.json relatorio_falhas.json relatorio_falhas.txt
```

---

## 🧠 Organização interna

O código foi organizado em adaptadores:

```text
AdaptadorYouTube
AdaptadorSpotify
AdaptadorGenericoYtdlp
```

Essa separação evita que uma plataforma quebre o funcionamento das outras.

Por exemplo:

- se o Spotify estiver sem credenciais, YouTube continua funcionando;
- se um link do Kwai não for suportado, TikTok e YouTube continuam;
- se o Facebook exigir cookies, os outros downloads continuam normalmente.

---

## 🤖 Uso de LLM no desenvolvimento

Este projeto foi desenvolvido com auxílio de uma LLM (Large Language Model).

A LLM foi usada para:

- sugerir a arquitetura modular;
- melhorar o tratamento de erros;
- separar responsabilidades por plataforma;
- refatorar funções;
- documentar o funcionamento;
- criar este README.

O código foi testado e ajustado manualmente durante o desenvolvimento.

---

## 📌 Observações importantes

- O funcionamento depende do `yt-dlp`.
- Algumas plataformas mudam frequentemente.
- Alguns links podem exigir cookies.
- Alguns links podem não ser suportados.
- Kwai pode funcionar parcialmente, dependendo do tipo do link.
- Facebook pode exigir login ou URL final do vídeo.
- Spotify não é usado para baixar áudio, apenas para metadados.

---

## 📄 Licença

Este projeto pode ser distribuído sob a licença MIT.

---

## 👤 Autor

Desenvolvido por Henrique Pires, com auxílio de LLM para estruturação, refatoração e documentação.
