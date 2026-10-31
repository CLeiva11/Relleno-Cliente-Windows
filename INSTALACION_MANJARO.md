# Instalación en Manjaro

La versión Manjaro usa el mismo portal, vínculo, cámaras y formato de datos que la
versión Windows. HikCentral permanece administrado en `https://127.0.0.1`, usuario
`admin`, y prueba las dos claves incluidas durante la compilación.

## Requisitos del equipo

```bash
sudo pacman -S --needed chromium libsecret xdg-utils tk
```

KWallet o el depósito de claves de la sesión debe estar habilitado. Los tokens del
portal y contraseñas de cámaras se guardan allí mediante `secret-tool`; nunca se
escriben en `config.json`.

## Instalar un paquete publicado

```bash
tar -xzf RellenoCliente-Manjaro-0.4.36.tar.gz
./install-manjaro.sh
```

La instalación es por usuario y no requiere `sudo`. Crea:

- aplicación en `~/.local/share/relleno-cliente/app`;
- lanzador `~/.local/bin/relleno-cliente`;
- acceso en el menú de aplicaciones;
- datos en `~/.local/share/RellenoCliente`;
- autoinicio XDG cuando el equipo queda vinculado.

Abra **Relleno Cliente**, vincule el centro con el código de un solo uso y configure
las cámaras igual que en Windows. Chromium automatiza el HikCentral local.

## Compilar

Use un entorno virtual con `requirements.txt` instalado:

```bash
export RELLENO_HIKCENTRAL_PASSWORDS='clave-actual|clave-anterior'
./build-manjaro.sh
```

El artefacto y su SHA-256 quedan en `dist/`. Para actualizaciones automáticas, el
portal debe publicar ese `.tar.gz` como plataforma `manjaro`; un `.exe` de Windows
se ignora de forma segura.
