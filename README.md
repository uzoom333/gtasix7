# GTASix7

Baixa vídeos com yt-dlp e gera um MP4 vertical com a marca GTASix7, crédito,
legendas da fala e áudio com volume ajustado. Informe o link e o @ do criador;
o resultado fica em `prontos/`. A postagem é manual.

Não precisa de ChatGPT, Qwen, chave de API ou assinatura. As legendas usam
Whisper na sua máquina; a edição e o áudio usam FFmpeg. Use vídeos combinados
com os criadores. O fluxo aceita acordos verbais e não exige comprovante.

## Instalação

Linux (Fedora/Debian/Ubuntu) ou macOS, com Git e Bash. No Windows, use WSL.
É necessário Python 3.10+; o instalador adiciona dependências e cria um ambiente
Python isolado em `.venv/`.

```bash
git clone https://github.com/uzoom333/gtasix7.git
cd gtasix7
./instalar.sh
export PATH="$HOME/.local/bin:$PATH"
```

Mantenha a linha `export PATH="$HOME/.local/bin:$PATH"` no `~/.bashrc` ou
`~/.zshrc` para os próximos terminais. O instalador usa sudo no Linux.
Se já usava a versão anterior, instale apenas as dependências das legendas:

```bash
git pull
./instalar-legendas.sh
```

Os scripts escolhem automaticamente o Python da `.venv/`. Para usar outro
interpretador, defina `GTASIX7_PYTHON`. O modelo Whisper `base` baixa no primeiro
uso com áudio e depois pode funcionar offline com os arquivos em cache. O download
do vídeo continua precisando de internet.

FFmpeg precisa de drawtext, subtitles/libass, loudnorm, AAC e libx264 ou libopenh264.
O projeto foi testado nesta máquina Fedora; os instaladores apt/Homebrew ainda
não foram executados aqui.

## Uso rápido

```bash
./baixar.sh 'https://www.instagram.com/reel/ID/' --criador @parceiro
```

Por padrão, ele:

- Baixa a melhor qualidade disponível até 4K, com o melhor áudio disponível.
- Gera vídeo vertical 9:16, em 2160×3840 quando a fonte tem 4K, ou 1080×1920 nos demais casos.
- Limita a saída a **60 segundos no total**: até 58 s do vídeo + 2 s de cartão final.
- Normaliza o volume com FFmpeg para alvo de −16 LUFS e pico de −1,5 dBTP.
- Transcreve a fala localmente e incorpora as legendas na imagem; também salva `.srt`.
- Preserva marca GTASix7, crédito `via @criador`, fundo desfocado e cartão final.

A fonte precisa oferecer 4K: o script não recupera detalhe ausente. Uma fonte
com largura ou altura de pelo menos 3840 pixels ativa a saída 4K automática.
`--resolucao 2160` força a saída 4K inclusive para fontes menores, fazendo upscale.
Renderizar 4K por CPU pode levar mais tempo.

Legendas não são tradução: `--idioma pt` informa que a fala está em português.
O reconhecimento pode errar nomes, música ou falas sobrepostas; revise o SRT e
use `--srt` para renderizar uma versão corrigida. Sem áudio, a saída recebe
silêncio. Se o detector não encontrar fala, não gera legendas. Ele não lê textos
que já estejam desenhados no vídeo.

## Ajustar edição, áudio e legendas

```bash
./baixar.sh 'LINK' --criador @parceiro \
  --gancho 'olha isso / no GTA 6' --legenda 'olha esse final' \
  --corte 3-45 --audio limpar --idioma pt
```

| Opção | Comportamento |
|---|---|
| `--resolucao auto` | 4K se a fonte tiver 4K; senão 1080×1920. Sempre vertical |
| `--resolucao 1080` | Saída 1080×1920, mais leve |
| `--resolucao 2160` | Saída 2160×3840, inclusive com upscale |
| `--duracao-max 30` | Limite total entre 3 e 60 s, incluindo o cartão de 2 s |
| `--audio normalizar` | Ajusta o volume, padrão |
| `--audio limpar` | Redução leve de ruído + ajuste de volume; não separa voz e música |
| `--audio original` | Mantém o nível original, com conversão para AAC |
| `--legendas auto` | Transcrição local incorporada ao vídeo, padrão |
| `--legendas nenhuma` | Desativa a transcrição; dispensa Whisper |
| `--modelo-whisper tiny` | Modelo menor e mais rápido; padrão `base`, opção `small` |
| `--idioma pt` | Idioma da fala; padrão `auto`, também aceita `en` e outros códigos |
| `--srt arquivo.srt` | Incorpora legenda pronta, sem transcrever |
| `--refazer` | Reprocessa um link já concluído com as opções atuais |

O SRT fornecido deve usar tempos relativos ao **início do trecho escolhido**, e
não ao começo do vídeo original. Legendas são exibidas só no corpo, sem cobrir o
cartão final. Não combine `--srt` com `--legendas nenhuma`.

O corte usa segundos (`3-25` ou `0.5-8.2`), deve caber no vídeo e ter fim maior
que início. Trechos maiores que o limite são truncados; sem corte, começa em 0.
Gancho aparece nos primeiros 3 s e aceita ` / ` para quebrar linha. Use texto curto.

Se o Instagram exigir sua sessão do navegador:

```bash
./baixar.sh 'LINK' --criador @parceiro --cookies-do-navegador firefox
```

Links privados, removidos ou indisponíveis para sua conta podem falhar. O projeto
usa o programa yt-dlp instalado localmente, sem extensão de navegador.

## Processar uma fila

O instalador cria `fila.txt`. Também pode copiar `fila.exemplo.txt` se ainda não
houver uma fila. Um vídeo por linha, só @ e URL obrigatórios:

```text
@parceiro | LINK | legenda | gancho / segunda linha | 3-25
```

```bash
./baixar.sh
./baixar.sh --fila outra-fila.txt --audio limpar --idioma pt
```

As opções de áudio, resolução e transcrição valem para toda a execução da fila.
Não use `|` dentro dos textos. Falhas não interrompem os demais itens; se algum
falhar, o comando termina com código 1. Executar de novo tenta os que falharam e
pula URLs concluídas. Para mudar as opções de uma URL concluída, use `--refazer`.
O histórico só é atualizado depois de baixar e editar com sucesso.

## Editar um arquivo local

```bash
./gtasix7.sh '/caminho/video.mp4' @parceiro 'legenda' 'gancho / linha 2' '3-25' \
  --audio limpar --idioma pt
```

O arquivo precisa continuar disponível no caminho informado. Para corrigir uma
legenda gerada, edite o `.srt` em `prontos/` e renderize de novo usando o vídeo
original em `recebidos/`:

```bash
./gtasix7.sh 'recebidos/ARQUIVO.mp4' @parceiro 'legenda' 'gancho' '3-25' \
  --srt 'prontos/LEGENDA_CORRIGIDA.srt'
```

Use o mesmo corte da primeira edição. Os nomes finais incluem uma chave das
opções e do conteúdo do SRT, para preservar versões diferentes.

## Arquivos e testes

MP4 H.264, 30 fps, áudio AAC estéreo a 48 kHz. `prontos/` recebe o vídeo, a legenda
do post (`.txt`) e, quando há fala ou SRT fornecido, a legenda sincronizada (`.srt`).
Fontes ficam em `recebidos/` e podem manter o contêiner original ou MKV para
preservar os codecs do download. Erros de download ficam em `logs/`; erros de
edição aparecem no terminal. Vídeos, cookies, ambiente Python, fila pessoal,
comprovantes e histórico não entram no Git. `pedido-autorizacao.md` é opcional.

```bash
python3 -m unittest -v test_gtasix7
```

A suíte não baixa modelos: usa vídeos sintéticos e cobre HTTP local com yt-dlp,
renderização 4K, limite de 60 s, áudio, SRT, silêncio, cortes, retomada e duplicatas.
Para testar também a transcrição real com fala sintetizada em português, instale
`espeak-ng`, prepare o modelo `base` e execute:

```bash
GTASIX7_TEST_ASR=1 ./.venv/bin/python -m unittest -v test_gtasix7
```

Tudo fica em diretórios temporários. Reels reais dependem do acesso à plataforma;
o teste HTTP local não valida login no Instagram.

Referências: [yt-dlp](https://github.com/yt-dlp/yt-dlp),
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) e
[filtros FFmpeg](https://ffmpeg.org/ffmpeg-filters.html).
