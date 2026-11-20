from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import nota
from tests import sinteticos

NOTA = str(Path(__file__).resolve().parents[1] / "nota.py")


def rodar(*args):
    return subprocess.run([sys.executable, NOTA, *args], capture_output=True, text=True)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nota_cli_"))
        self.media = self.tmp / "media"
        self.media.mkdir()
        c = sinteticos.clipes()
        shutil.copy(c["parado"], self.media / "A001.mp4")
        shutil.copy(c["pan_esq"], self.media / "A002.MOV")
        (self.media / "quebrado.mp4").write_bytes(b"nao e video")
        (self.media / "notas.txt").write_text("ignorar")
        self.saida = self.tmp / "analise"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def analisar(self):
        return rodar("analisar", str(self.media), "--saida", str(self.saida), "--sem-hw")

    def test_analisar_grava_sidecars_e_falhas(self):
        r = self.analisar()
        self.assertEqual(r.returncode, 0, r.stderr)
        sidecars = sorted((self.saida / "nota").glob("*.nota.json"))
        self.assertEqual(len(sidecars), 2)
        self.assertTrue(sidecars[0].name.startswith("A001_"))
        falhas = json.loads((self.saida / "nota" / "falhas.json").read_text())
        self.assertEqual(list(falhas), [str((self.media / "quebrado.mp4").resolve())])

    def test_workers_em_paralelo_dao_o_mesmo_resultado(self):
        um = self.tmp / "um" / "analise"
        tres = self.tmp / "tres" / "analise"
        for saida, n in ((um, "1"), (tres, "3")):
            r = rodar("analisar", str(self.media), "--saida", str(saida), "--sem-hw", "--workers", n)
            self.assertEqual(r.returncode, 0, r.stderr)
        nomes = sorted(p.name for p in (um / "nota").glob("*.nota.json"))
        self.assertEqual(len(nomes), 2)
        self.assertEqual(nomes, sorted(p.name for p in (tres / "nota").glob("*.nota.json")))
        for nome in nomes:
            self.assertEqual(json.loads((um / "nota" / nome).read_text()),
                             json.loads((tres / "nota" / nome).read_text()))
        falhas = json.loads((tres / "nota" / "falhas.json").read_text())
        self.assertEqual(list(falhas), [str((self.media / "quebrado.mp4").resolve())])

    def test_workers_invalido(self):
        r = rodar("analisar", str(self.media), "--saida", str(self.saida), "--workers", "0")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.saida / "nota").exists())

    def test_segunda_rodada_pula_o_que_ja_foi_analisado(self):
        self.analisar()
        r = self.analisar()
        self.assertEqual(r.stdout.count("já analisado"), 2)

    def test_avisa_quando_refaz_analise_antiga_sem_colunas_novas(self):
        self.analisar()
        r = self.analisar()
        self.assertNotIn("refazendo", r.stdout)
        arquivo = sorted((self.saida / "nota").glob("A001_*.nota.json"))[0]
        dados = json.loads(arquivo.read_text())
        del dados["quadros"]["cam_rot"]
        arquivo.write_text(json.dumps(dados))
        r = self.analisar()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("refazendo 1 análise(s) antiga(s) sem as colunas novas (detalhe, luma, rotação)", r.stdout)
        self.assertEqual(r.stdout.count("já analisado"), 1)
        self.assertIn("cam_rot", json.loads(arquivo.read_text())["quadros"])

    def test_nao_escreve_na_pasta_de_midia(self):
        antes = sorted(p.name for p in self.media.iterdir())
        self.analisar()
        self.assertEqual(sorted(p.name for p in self.media.iterdir()), antes)

    def test_recusa_saida_fora_de_analise(self):
        fora = self.tmp / "outra_pasta"
        r = rodar("analisar", str(self.media), "--saida", str(fora), "--sem-hw")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(fora.exists())

    def test_selecionar_gera_selects(self):
        self.analisar()
        r = rodar("selecionar", "--preset", "imovel", "--saida", str(self.saida))
        self.assertEqual(r.returncode, 0, r.stderr)
        s = json.loads((self.saida / "selects.json").read_text())
        self.assertEqual(s["preset"], "imovel")
        self.assertEqual(s["versao_motor"], "1.2")
        self.assertIsNone(s["miniatura_perfil"])
        self.assertIsNone(s["miniatura_filtro"])
        self.assertEqual(len(s["falhas"]), 1)
        for campo in ("trechos", "avisos", "filtros", "gerado_em"):
            self.assertIn(campo, s)

    def test_selecionar_grava_perfil_de_log(self):
        self.analisar()
        r = rodar("selecionar", "--preset", "log_cinema", "--saida", str(self.saida))
        self.assertEqual(r.returncode, 0, r.stderr)
        s = json.loads((self.saida / "selects.json").read_text())
        self.assertEqual(s["miniatura_perfil"], "auto")
        self.assertIsNone(s["miniatura_filtro"])

    def test_selecionar_filtra_camera(self):
        self.analisar()
        rodar("selecionar", "--preset", "broll_acao", "--camera", "pan_esq", "--saida", str(self.saida))
        s = json.loads((self.saida / "selects.json").read_text())
        self.assertEqual(s["filtros"]["camera"], ["pan_esq"])
        self.assertTrue(s["trechos"])
        self.assertTrue(all(t["camera"]["tipo"] == "pan_esq" for t in s["trechos"]))

    def test_camera_desconhecida_da_erro_legivel(self):
        r = rodar("selecionar", "--camera", "parada,panorama", "--saida", str(self.saida))
        self.assertEqual(r.returncode, 2)
        self.assertIn("panorama", r.stderr)
        self.assertIn("pan_esq", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertFalse((self.saida / "selects.json").exists())

    def test_flag_desconhecida_da_erro_legivel(self):
        r = rodar("selecionar", "--excluir", "blur,borrado", "--saida", str(self.saida))
        self.assertEqual(r.returncode, 2)
        self.assertIn("borrado", r.stderr)
        self.assertIn("tremido", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_preset_inexistente_da_erro_legivel(self):
        self.analisar()
        r = rodar("selecionar", "--preset", "nao_existe", "--saida", str(self.saida))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("preset não encontrado", r.stderr)

    def test_pasta_oculta_e_ignorada_e_extensoes_sao_contadas(self):
        oculta = self.media / ".Trashes"
        oculta.mkdir()
        shutil.copy(sinteticos.clipes()["parado"], oculta / "lixo.mp4")
        r = self.analisar()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("lixo.mp4", r.stdout + r.stderr)
        self.assertEqual(len(list((self.saida / "nota").glob("lixo_*.nota.json"))), 0)
        self.assertIn("1 arquivo(s) ignorado(s) pela extensão", r.stdout)

    def test_mudar_amostras_reanalisa(self):
        self.analisar()
        r = rodar("analisar", str(self.media), "--saida", str(self.saida), "--sem-hw", "--amostras", "8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("já analisado"), 0, r.stdout)
        s = json.loads(sorted((self.saida / "nota").glob("A001_*.nota.json"))[0].read_text())
        self.assertEqual(s["amostras_por_s"], 8.0)

    def test_selecionar_e_relatorio_so_com_as_pastas_pedidas(self):
        outra = self.tmp / "media_b"
        outra.mkdir()
        shutil.copy(sinteticos.clipes()["parado"], outra / "B001.mp4")
        self.analisar()
        rodar("analisar", str(outra), "--saida", str(self.saida), "--sem-hw")
        tudo = rodar("selecionar", "--preset", "broll_acao", "--saida", str(self.saida))
        self.assertEqual(tudo.returncode, 0, tudo.stderr)
        todos = {Path(t["caminho"]).name for t in json.loads((self.saida / "selects.json").read_text())["trechos"]}
        self.assertIn("B001.mp4", todos)

        r = rodar("selecionar", str(self.media), "--preset", "broll_acao", "--saida", str(self.saida))
        self.assertEqual(r.returncode, 0, r.stderr)
        s = json.loads((self.saida / "selects.json").read_text())
        self.assertTrue(s["trechos"])
        raiz = str(self.media.resolve())
        self.assertTrue(all(t["caminho"].startswith(raiz + "/") for t in s["trechos"]))
        self.assertTrue(all(f["caminho"].startswith(raiz + "/") for f in s["falhas"]))

        rodar("selecionar", "--preset", "broll_acao", "--saida", str(self.saida))
        r = rodar("relatorio", str(outra), "--saida", str(self.saida), "--top", "5")
        self.assertEqual(r.returncode, 0, r.stderr)
        md = (self.saida / "selects.md").read_text()
        self.assertIn("B001.mp4", md)
        self.assertNotIn("A001.mp4", md)
        self.assertNotIn("quebrado.mp4", md)

    def test_pasta_que_sumiu_ainda_filtra_e_avisa(self):
        # Cartão ejetado depois do analisar: a pasta não existe mais, mas os sidecars apontam para ela.
        self.analisar()
        raiz = str(self.media.resolve())
        self.media.rename(self.tmp / "ejetado")
        r = rodar("selecionar", raiz, "--preset", "broll_acao", "--saida", str(self.saida))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("não existe", r.stderr)
        self.assertIn(raiz, r.stderr)
        s = json.loads((self.saida / "selects.json").read_text())
        self.assertTrue(s["trechos"])
        self.assertTrue(all(t["caminho"].startswith(raiz + "/") for t in s["trechos"]))
        r = rodar("selecionar", str(self.tmp / "nunca_existiu"), "--preset", "broll_acao", "--saida", str(self.saida))
        self.assertIn("não existe", r.stderr)
        self.assertEqual(json.loads((self.saida / "selects.json").read_text())["trechos"], [])


class TestColetar(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nota_col_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def criar(self, rel):
        f = self.tmp / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"")
        return str(f.resolve())

    def test_extensoes_novas_e_pastas_puladas(self):
        bons = [self.criar(r) for r in ("a/C0001.MTS", "a/C0002.m2ts", "a/C0003.mpg", "M4ROOT/CLIP/C0004.MP4")]
        for r in (".oculta/x.mp4", "a/.cache/y.mov", "M4ROOT/SUB/C0004S03.MP4", "a/z.txt", "a/._C0001.MTS"):
            self.criar(r)
        videos, pulados = nota.coletar_com_contagem([str(self.tmp)])
        self.assertEqual(videos, sorted(bons))
        self.assertEqual(pulados, 1)
        self.assertEqual(nota.coletar([str(self.tmp)]), sorted(bons))

    def test_arquivo_passado_direto_e_aceito(self):
        f = self.criar("a/C0001.mp4")
        self.assertEqual(nota.coletar([f]), [f])


if __name__ == "__main__":
    unittest.main()
