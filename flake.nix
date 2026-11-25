{
  description = "Bugsito (antes Jarvis) — Asistente de voz interactivo con bola de energía Wayland y motor Multi-LLM Genkit";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          pythonEnv = pkgs.python3.withPackages (ps: [
            ps.pygobject3
            ps.pycairo
          ]);
          typelibPath = pkgs.lib.makeSearchPath "lib/girepository-1.0" [
            pkgs.glib.out
            pkgs.pango.out
            pkgs.gtk3
            pkgs.gtk-layer-shell
            pkgs.gdk-pixbuf
            pkgs.atk
            pkgs.harfbuzz
            pkgs.gobject-introspection
          ];
          runtimeBins = pkgs.lib.makeBinPath [
            pkgs.ffmpeg
            pkgs.whisper-cpp
            pkgs.piper-tts
            pkgs.espeak-ng
            pkgs.wtype
            pkgs.pulseaudio
            pkgs.curl
          ];
        in
        {
          default = pkgs.writeShellScriptBin "bugsito" ''
            export GDK_BACKEND=wayland
            export GI_TYPELIB_PATH="${typelibPath}"
            export PATH="${runtimeBins}:$PATH"
            export PYTHONPATH="${self}:''${PYTHONPATH:-}"
            exec ${pythonEnv}/bin/python3 -m bugsito.cli "$@"
          '';
        }
      );
    };
}
