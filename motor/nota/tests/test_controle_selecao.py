"""P1 do PRD: flags preferir e forçar, motion blur, submétricas, ajuste por clipe e ordenação."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import presets
from segmentos import (agrupar, flags_quadros, forcados_quadros, montar_selects, normalizar, notas_quadros,
                       trechos_do_clipe)
from tests import sinteticos
from tests.test_segmentos import DT, preset, quadros_fake

NOTA = str(Path(__file__).resolve().parents[1] / "nota.py")


def sidecar(nome, n=40, **over):
    return {"caminho": f"/m/{nome}", "fps": 24.0, "duracao": n * DT, "amostras_por_s": 1 / DT,
            "quadros": quadros_fake(n, **over)}


class TestFlagsPreferirEForcar(unittest.TestCase):
    def test_preferir_multiplica_por_1_2(self):
        q = quadros_fake(2, esmagado=[0.0, 0.2])
        p = preset()
        norm = normalizar(q, p)
        flags = flags_quadros(q, norm, p)
        base = notas_quadros(norm, flags, p)[1]  # esmagado desfavorece (×0,6) por padrão
        p["flags"]["esmagado"] = "preferir"
        self.assertAlmostEqual(notas_quadros(norm, flags, p)[1], min(base / 0.6 * 1.2, 1.0))

    def test_forcar_inclui_quadro_que_seria_excluido(self):
        q = quadros_fake(2, estourado=[0.0, 0.5])
        p = preset()
        p["flags"]["estourado"] = "forcar"
        norm = normalizar(q, p)
        flags = flags_quadros(q, norm, p)
        notas = notas_quadros(norm, flags, p)
        self.assertIsNotNone(notas[1])
        self.assertEqual(forcados_quadros(flags, p), [False, True])

    def test_excluir_de_outra_flag_vence_forcar(self):
        p = preset()
        p["flags"]["estourado"] = "forcar"
        self.assertEqual(forcados_quadros([["estourado", "blur"]], p), [False])
        norm = {k: [0.1] for k in ("foco", "exposicao", "estabilidade", "movimento")}
        self.assertIsNone(notas_quadros(norm, [["estourado", "blur"]], p)[0])

    def test_trecho_forcado_entra_abaixo_da_nota_minima(self):
        p = preset()
        notas = [0.3] * 12
        self.assertEqual(agrupar(notas, [False] * 12, DT, p), [])
        self.assertEqual(agrupar(notas, [False] * 12, DT, p, forcados=[True] * 12), [(0, 11)])

    def test_comportamentos_novos_sao_aceitos_no_preset(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "p.json"
            arq.write_text(json.dumps({"flags": {"tremido": "preferir", "estourado": "forcar"}}))
            p = presets.carregar(str(arq))
        self.assertEqual((p["flags"]["tremido"], p["flags"]["estourado"]), ("preferir", "forcar"))


class TestMotionBlur(unittest.TestCase):
    def test_borrado_parado_e_blur(self):
        q = quadros_fake(4, nitidez=[1000.0, 1000.0, 1000.0, 50.0])
        p = preset(foco_piso_absoluto=10.0)
        self.assertEqual(flags_quadros(q, normalizar(q, p), p)[3], ["blur"])

    def test_borrado_com_camera_rapida_e_blur_movimento(self):
        q = quadros_fake(4, nitidez=[1000.0, 1000.0, 1000.0, 50.0], cam_dx=[0.0, 0.0, 0.0, 0.3])
        p = preset(foco_piso_absoluto=10.0)
        self.assertEqual(flags_quadros(q, normalizar(q, p), p)[3], ["blur_movimento"])

    def test_borrado_com_assunto_rapido_e_blur_movimento(self):
        q = quadros_fake(4, nitidez=[1000.0, 1000.0, 1000.0, 50.0], movimento_assunto=[0.0, 0.0, 0.0, 0.2])
        p = preset(foco_piso_absoluto=10.0)
        self.assertIn("blur_movimento", flags_quadros(q, normalizar(q, p), p)[3])

    def test_padrao_desfavorece_em_vez_de_excluir(self):
        self.assertEqual(presets.PADRAO["flags"]["blur_movimento"], "desfavorecer")


class TestSubmetricas(unittest.TestCase):
    def test_padrao_nao_muda_movimento(self):
        q = quadros_fake(3, movimento_assunto=[0.0, 0.04, 0.2], cam_dx=[0.0, 0.3, 0.0])
        p = preset()
        mov = normalizar(q, p)["movimento"]
        self.assertAlmostEqual(float(mov[0]), 1.0)
        self.assertAlmostEqual(float(mov[1]), 1.0 - 0.04 / p["movimento_tolerancia"])
        self.assertEqual(float(mov[2]), 0.0)

    def test_peso_da_camera_no_movimento(self):
        q = quadros_fake(2, cam_dx=[0.0, 0.3])
        p = preset()
        p["submetricas"]["movimento"] = {"assunto": 0.0, "camera": 1.0}
        p["camera_vel_alvo"], p["camera_vel_tolerancia"] = 0.0, 0.1
        mov = normalizar(q, p)["movimento"]
        self.assertAlmostEqual(float(mov[0]), 1.0)
        self.assertEqual(float(mov[1]), 0.0)

    def test_peso_zero_desliga_componente_da_exposicao(self):
        q = quadros_fake(2, estourado=[0.0, 0.1])
        p = preset()
        self.assertLess(float(normalizar(q, p)["exposicao"][1]), 1.0)
        p["submetricas"]["exposicao"]["estourado"] = 0.0
        self.assertAlmostEqual(float(normalizar(q, p)["exposicao"][1]), 1.0)

    def test_preset_parcial_mescla_submetricas(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "p.json"
            arq.write_text(json.dumps({"submetricas": {"movimento": {"camera": 0.5}}}))
            p = presets.carregar(str(arq))
        self.assertEqual(p["submetricas"]["movimento"], {"assunto": 1.0, "camera": 0.5})
        self.assertEqual(p["submetricas"]["exposicao"], presets.PADRAO["submetricas"]["exposicao"])

    def test_peso_negativo_e_recusado(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "p.json"
            arq.write_text(json.dumps({"submetricas": {"exposicao": {"brilho": -1}}}))
            with self.assertRaises(ValueError):
                presets.carregar(str(arq))


class TestAjustePorClipe(unittest.TestCase):
    def test_excluir_clipe(self):
        p = preset()
        r = montar_selects([sidecar("A.MP4"), sidecar("B.MP4")], p, ajustes={"B.MP4": {"excluir": True}})
        self.assertEqual({t["caminho"] for t in r["trechos"]}, {"/m/A.MP4"})

    def test_chave_por_nome_sem_extensao_e_sem_maiusculas(self):
        p = preset()
        r = montar_selects([sidecar("C0261.MP4")], p, ajustes={"c0261": {"excluir": True}})
        self.assertEqual(r["trechos"], [])

    def test_sobrescreve_chave_do_preset(self):
        p = preset()
        base, _ = trechos_do_clipe(sidecar("A.MP4", n=200), p)
        r = montar_selects([sidecar("A.MP4", n=200)], p, ajustes={"A.MP4": {"duracao_max_s": 5.0}})
        self.assertGreater(len(r["trechos"]), len(base))
        self.assertTrue(all(t["duracao_s"] <= 5.0 + 1e-9 for t in r["trechos"]))

    def test_troca_o_preset(self):
        p = preset()
        alvo = presets.carregar("entrevista")
        aplicado = presets.aplicar_ajuste(p, {"preset": "entrevista"})
        self.assertEqual(aplicado["pesos"], alvo["pesos"])

    def test_chave_invalida_e_recusada(self):
        with self.assertRaises(ValueError):
            presets.aplicar_ajuste(preset(), {"nota_minn": 0.8})

    def test_aviso_para_ajuste_sem_clipe(self):
        r = montar_selects([sidecar("A.MP4")], preset(), ajustes={"ZZZ.MP4": {"excluir": True}})
        self.assertEqual(r["ajustes_sem_clipe"], ["ZZZ.MP4"])


class TestOrdem(unittest.TestCase):
    def setUp(self):
        self.t = [sidecar("B.MP4", n=40), sidecar("A.MP4", n=20, nitidez=[1000.0] * 20, brilho=[0.7] * 20)]

    def test_por_gravacao(self):
        r = montar_selects(self.t, preset(), ordem="gravacao")
        chaves = [(t["caminho"], t["inicio_s"]) for t in r["trechos"]]
        self.assertEqual(chaves, sorted(chaves))

    def test_por_duracao(self):
        r = montar_selects(self.t, preset(), ordem="duracao")
        duracoes = [t["duracao_s"] for t in r["trechos"]]
        self.assertEqual(duracoes, sorted(duracoes, reverse=True))

    def test_ordem_invalida(self):
        with self.assertRaises(ValueError):
            montar_selects(self.t, preset(), ordem="tamanho")


class TestDescartados(unittest.TestCase):
    """Painel de seleção ao vivo: o gráfico mostra também os trechos que os filtros tiraram, com o motivo."""

    def test_descartados_por_nota_minima_e_maxima(self):
        base = montar_selects([sidecar("A001.mp4")], preset())
        self.assertTrue(base["trechos"])
        self.assertEqual(base["descartados"], [])
        n = len(base["trechos"])
        r = montar_selects([sidecar("A001.mp4")], preset(), nota_min=1.01)
        self.assertEqual((r["trechos"], [d["motivo"] for d in r["descartados"]]), ([], ["nota_min"] * n))
        r = montar_selects([sidecar("A001.mp4")], preset(), nota_max=0.0)
        self.assertEqual([d["motivo"] for d in r["descartados"]], ["nota_max"] * n)
        self.assertEqual(r["descartados"][0]["caminho"], "/m/A001.mp4")

    def test_descartados_por_camera_e_max_por_clipe(self):
        r = montar_selects([sidecar("A001.mp4")], preset(), cameras=["whip_pan"])
        self.assertTrue(r["descartados"])
        self.assertTrue(all(d["motivo"] == "camera" for d in r["descartados"]))
        r = montar_selects([sidecar("A001.mp4")], preset(), max_por_clipe=1)
        self.assertEqual(len(r["trechos"]), 1)
        self.assertTrue(all(d["motivo"] == "max_por_clipe" for d in r["descartados"]))


class TestSegundosPorFlag(unittest.TestCase):
    def test_conta_os_segundos_de_cada_problema_mesmo_ignorado(self):
        from segmentos import segundos_por_flag
        sc = sidecar("A001.mp4", n=10, estourado=[0.0] * 6 + [0.5] * 4)
        p = preset()
        p["flags"]["estourado"] = "ignorar"
        self.assertAlmostEqual(segundos_por_flag(sc, p)["estourado"], 4 * DT)
        self.assertEqual(segundos_por_flag(sidecar("B.mp4", n=10), p).get("estourado", 0), 0)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nota_p1_"))
        media = self.tmp / "media"
        media.mkdir()
        c = sinteticos.clipes()
        shutil.copy(c["parado"], media / "A001.mp4")
        shutil.copy(c["pan_esq"], media / "A002.mp4")
        self.saida = self.tmp / "analise"
        subprocess.run([sys.executable, NOTA, "analisar", str(media), "--sem-hw", "--saida", str(self.saida)],
                       check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def selecionar(self, *extra):
        r = subprocess.run([sys.executable, NOTA, "selecionar", "--preset", "broll_acao", "--saida",
                            str(self.saida), *extra], capture_output=True, text=True)
        return r, (json.loads((self.saida / "selects.json").read_text()) if r.returncode == 0 else None)

    def test_ajustes_json_na_pasta_de_analise(self):
        (self.saida / "ajustes.json").write_text(json.dumps({"A002": {"excluir": True}}))
        r, s = self.selecionar()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(s["trechos"])
        self.assertTrue(all("A001" in t["caminho"] for t in s["trechos"]))

    def test_ajustes_invalido_da_erro_legivel(self):
        (self.saida / "ajustes.json").write_text(json.dumps({"A002": {"nota_minn": 1}}))
        r, _ = self.selecionar()
        self.assertEqual(r.returncode, 2)
        self.assertIn("A002", r.stderr)

    def test_ordem_na_cli(self):
        r, s = self.selecionar("--ordem", "gravacao")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(s["filtros"]["ordem"], "gravacao")
        chaves = [(t["caminho"], t["inicio_s"]) for t in s["trechos"]]
        self.assertEqual(chaves, sorted(chaves))

    def test_com_descartados_grava_os_trechos_tirados(self):
        r, s = self.selecionar()
        self.assertNotIn("descartados", s)
        r, s = self.selecionar("--com-descartados", "--max-por-clipe", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("descartados", s)
        self.assertTrue(all(d["motivo"] == "max_por_clipe" for d in s["descartados"]))
        self.assertEqual(s["material"]["clipes"], 2)
        self.assertIsInstance(s["material"]["flags_s"], dict)
        self.assertGreater(s["material"]["duracao_s"], 0)

    def test_arquivo_grava_outro_selects_sem_tocar_no_principal(self):
        r, _ = self.selecionar()
        principal = (self.saida / "selects.json").read_text()
        r = subprocess.run([sys.executable, NOTA, "selecionar", "--preset", "broll_acao", "--saida", str(self.saida),
                            "--arquivo", "selects_painel.json", "--max-por-clipe", "1"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.saida / "selects_painel.json").exists())
        self.assertEqual((self.saida / "selects.json").read_text(), principal)
        r = subprocess.run([sys.executable, NOTA, "selecionar", "--saida", str(self.saida), "--arquivo", "../x.json"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_flag_desconhecida_no_excluir_inclui_blur_movimento(self):
        r, _ = self.selecionar("--excluir", "blur_movimento")
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
