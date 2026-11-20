"""RAW que o ffmpeg não lê: N-RAW (.nev) e sequências CinemaDNG (uma pasta = um clipe)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import davinci
import nota
from proxy import NAO_DECODIFICA, quadros_dng


def criar(pasta: Path, nomes):
    pasta.mkdir(parents=True, exist_ok=True)
    for n in nomes:
        (pasta / n).write_bytes(b"")


class TestFormatos(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_sequencia_cinemadng(self):
        pasta = self.tmp / "A001_C003"
        criar(pasta, [f"A001_C003_{i:06d}.dng" for i in range(100, 130)] + ["A001_C003.wav", ".DS_Store"])
        quadros = quadros_dng(pasta)
        self.assertEqual(len(quadros), 30)
        self.assertEqual(quadros[0].name, "A001_C003_000100.dng")
        self.assertEqual(quadros[-1].name, "A001_C003_000129.dng")

    def test_fotos_soltas_nao_sao_sequencia(self):
        criar(self.tmp / "fotos", [f"DSC{n:05d}.dng" for n in range(2700, 2800, 3)])   # 34 fotos, com buracos
        self.assertIsNone(quadros_dng(self.tmp / "fotos"))
        criar(self.tmp / "curta", [f"B_{i:04d}.dng" for i in range(10)])
        self.assertIsNone(quadros_dng(self.tmp / "curta"))
        self.assertIsNone(quadros_dng(self.tmp / "nao_existe"))

    def test_nev_vai_direto_para_o_proxy(self):
        self.assertIn(".nev", NAO_DECODIFICA)

    def test_coleta_junta_a_sequencia_e_ignora_fotos(self):
        criar(self.tmp / "cartao" / "A001_C003", [f"A001_C003_{i:06d}.dng" for i in range(30)])
        criar(self.tmp / "cartao" / "fotos", [f"DSC{n:05d}.dng" for n in range(0, 90, 3)])
        criar(self.tmp / "cartao", ["DSC_0001.NEV", "C0001.MP4"])
        videos, pulados = nota.coletar_com_contagem([str(self.tmp / "cartao")])
        nomes = sorted(Path(v).name for v in videos)
        self.assertEqual(nomes, ["A001_C003", "C0001.MP4", "DSC_0001.NEV"])
        self.assertEqual(pulados, 30)

    def test_pasta_dng_sem_proxy_da_erro_de_proxy(self):
        pasta = self.tmp / "A001_C003"
        criar(pasta, [f"A001_C003_{i:06d}.dng" for i in range(30)])
        video, dados, erro = nota._analisar_um(str(pasta), 4.0, 320, False)
        self.assertIsNone(dados)
        self.assertIn("proxy", erro)

    def test_caminho_da_sequencia_no_resolve_vira_a_pasta(self):
        self.assertEqual(davinci.caminho_no_resolve("/c/A001_C003/A001_C003_[000100-000129].dng"), "/c/A001_C003")
        self.assertEqual(davinci.caminho_no_resolve("/c/A001_C003/A001_C003_[000100-000129].DNG"), "/c/A001_C003")
        self.assertEqual(davinci.caminho_no_resolve("/c/C0001.MP4"), "/c/C0001.MP4")
        self.assertEqual(davinci.caminho_no_resolve(""), "")
        self.assertIsNone(davinci.caminho_no_resolve(None))

    def test_tamanho_e_data_da_pasta_vem_dos_quadros(self):
        pasta = self.tmp / "A001_C003"
        criar(pasta, [f"A001_C003_{i:06d}.dng" for i in range(100, 130)])
        for i, f in enumerate(quadros_dng(pasta)):
            f.write_bytes(b"x" * (i + 1))
            os.utime(f, (1_700_000_000 + i, 1_700_000_000 + i))
        tamanho, mtime = nota._tamanho_e_data(str(pasta))
        self.assertEqual((tamanho, mtime), (sum(range(1, 31)), 1_700_000_029))
        (pasta / ".DS_Store").write_bytes(b"lixo do Finder")   # aparece depois: não mexe na foto do clipe
        (pasta / "A001_C003.wav").write_bytes(b"audio")
        self.assertEqual(nota._tamanho_e_data(str(pasta)), (tamanho, mtime))
        os.utime(quadros_dng(pasta)[3], (1_800_000_000, 1_800_000_000))   # quadro mexido: muda
        self.assertEqual(nota._tamanho_e_data(str(pasta)), (tamanho, 1_800_000_000))

    def test_arquivo_continua_pelo_stat(self):
        f = self.tmp / "C0001.MP4"
        f.write_bytes(b"abc")
        st = os.stat(f)
        self.assertEqual(nota._tamanho_e_data(str(f)), (st.st_size, st.st_mtime))

    def test_pasta_dng_fica_atualizada_apesar_do_ds_store(self):
        pasta = self.tmp / "A001_C003"
        criar(pasta, [f"A001_C003_{i:06d}.dng" for i in range(100, 130)])
        tamanho, mtime = nota._tamanho_e_data(str(pasta))
        sidecar = self.tmp / "s.nota.json"
        sidecar.write_text(json.dumps({"versao_motor": nota.VERSAO_MOTOR, "tamanho": tamanho, "mtime": mtime,
                                       "amostras_por_s": 4.0, "largura": 320, "metricas_puladas": [],
                                       "quadros": {c: [] for c in nota.COLUNAS_QUADRO}}))
        self.assertTrue(nota._atualizado(sidecar, str(pasta), 4.0, 320, []))
        (pasta / ".DS_Store").write_bytes(b"x")
        self.assertTrue(nota._atualizado(sidecar, str(pasta), 4.0, 320, []))


if __name__ == "__main__":
    unittest.main()
