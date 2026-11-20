"""Submétricas bipolares: preferências no preset mudam a nota no sentido certo; padrão não muda nada."""
from __future__ import annotations

import unittest

import numpy as np

import presets
import segmentos
from tests.test_lote1 import sidecar
from tests.test_segmentos import quadros_fake


def padrao(**over):
    p = presets._mesclar(presets.PADRAO, over, "teste")
    presets._validar(p)
    p["nome"] = "teste"
    return p


def com_colunas(n, **over):
    q = quadros_fake(n, **over)
    q.setdefault("detalhe", [0.05] * n)
    q.setdefault("luma_p01", [0.1] * n)
    q.setdefault("luma_p99", [0.9] * n)
    return q


def efeito(teste, nome, q, mais, menos, sentidos=("+", "-")):
    """Ligar a preferência +1 afasta o quadro `mais` (polo +) do `menos`; −1 faz o contrário.

    Nitidez e assunto são espelhos da base (foco = nitidez, movimento padrão = assunto parado): ligados, substituem
    a base, então o sentido que a base já premia dá a mesma ordem; `sentidos` diz quais sentidos o teste confere.
    """
    metrica = segmentos.METRICA_DA_PREFERENCIA[nome]
    zero = segmentos.normalizar(q, padrao())[metrica]
    d0 = zero[mais] - zero[menos]
    if "+" in sentidos:
        pos = segmentos.normalizar(q, padrao(preferencias={nome: 1.0}))[metrica]
        teste.assertGreater(pos[mais] - pos[menos], d0 + 1e-6, f"{nome} +1")
    if "-" in sentidos:
        neg = segmentos.normalizar(q, padrao(preferencias={nome: -1.0}))[metrica]
        teste.assertLess(neg[mais] - neg[menos], d0 - 1e-6, f"{nome} -1")


class TestPadrao(unittest.TestCase):
    def test_todas_as_preferencias_existem_e_comecam_em_zero(self):
        self.assertEqual(set(presets.PADRAO["preferencias"]), set(presets.PREFERENCIAS))
        self.assertTrue(all(v == 0 for v in presets.PADRAO["preferencias"].values()))
        self.assertEqual(set(segmentos.METRICA_DA_PREFERENCIA), set(presets.PREFERENCIAS))

    def test_padrao_nao_muda_a_nota(self):
        q = com_colunas(8, nitidez=[1000, 900, 400, 1000, 1000, 300, 1000, 1000], brilho=[0.5, 0.6] * 4,
                        cam_dx=[0.0, 0.05] * 4, movimento_assunto=[0.0, 0.04] * 4)
        antes = segmentos._normalizar_base(q, padrao())
        agora = segmentos.normalizar(q, padrao())
        self.assertEqual(set(agora), set(antes))
        for k in antes:
            np.testing.assert_allclose(agora[k], antes[k])

    def test_preset_rejeita_nome_e_valor_invalidos(self):
        with self.assertRaises(ValueError):
            padrao(preferencias={"nitidex": 0.5})
        with self.assertRaises(ValueError):
            padrao(preferencias={"detalhe": 1.5})
        with self.assertRaises(ValueError):
            padrao(preferencias={"detalhe": True})


class TestCadaPreferencia(unittest.TestCase):
    def test_nitidez(self):
        # A nota base do foco já é a nitidez: +1 não muda a ordem; -1 (prefere suave) inverte a tendência.
        efeito(self, "nitidez", com_colunas(4, nitidez=[1000, 1000, 400, 400]), 0, 2, sentidos=("-",))

    def test_detalhe(self):
        efeito(self, "detalhe", com_colunas(4, detalhe=[0.10, 0.10, 0.02, 0.02]), 0, 2)

    def test_estab_foco(self):
        nit = [1000.0] * 6 + [1000.0, 400.0] * 3
        efeito(self, "estab_foco", com_colunas(12, nitidez=nit), 1, 8)

    def test_folga_cor(self):
        efeito(self, "folga_cor", com_colunas(4, luma_p01=[0.1, 0.1, 0.0, 0.0], luma_p99=[0.9, 0.9, 1.0, 1.0]), 0, 2)

    def test_flicker(self):
        b = [0.5] * 4 + [0.5, 0.62, 0.5, 0.62, 0.5, 0.62]
        efeito(self, "flicker", com_colunas(10, brilho=b), 1, 5)

    def test_luma(self):
        efeito(self, "luma", com_colunas(4, brilho=[0.7, 0.7, 0.3, 0.3]), 0, 2)

    def test_contraste(self):
        efeito(self, "contraste", com_colunas(4, contraste=[0.5, 0.5, 0.1, 0.1]), 0, 2)

    def test_camera(self):
        efeito(self, "camera", com_colunas(4, cam_dx=[0.0, 0.0, 0.08, 0.08]), 0, 2)

    def test_assunto(self):
        # A nota base do movimento já premia assunto parado (movimento_alvo 0): -1 não muda a ordem.
        efeito(self, "assunto", com_colunas(4, movimento_assunto=[0.06, 0.06, 0.02, 0.02]), 0, 2, sentidos=("+",))

    def test_estab_movimento(self):
        dx = [0.03] * 4 + [0.0, 0.06, 0.0, 0.06, 0.0, 0.06]
        efeito(self, "estab_movimento", com_colunas(10, cam_dx=dx), 1, 6)

    def test_peso_maior_puxa_mais(self):
        q = com_colunas(4, detalhe=[0.10, 0.10, 0.02, 0.02])
        fraco = segmentos.normalizar(q, padrao(preferencias={"detalhe": 0.2}))["foco"]
        forte = segmentos.normalizar(q, padrao(preferencias={"detalhe": 1.0}))["foco"]
        self.assertGreater(forte[0] - forte[2], fraco[0] - fraco[2])


class TestEspelho(unittest.TestCase):
    """nitidez e assunto ligados substituem a base da métrica (Σ|p|·x / Σ|p|)."""

    def test_nitidez_negativa_inverte_o_foco(self):
        q = com_colunas(4, nitidez=[1000, 1000, 400, 400])
        base = segmentos.normalizar(q, padrao())["foco"]
        neg = segmentos.normalizar(q, padrao(preferencias={"nitidez": -1.0}))["foco"]
        np.testing.assert_allclose(neg, 1.0 - base)
        self.assertGreater(neg[2], neg[0])   # agora prefere o suave

    def test_nitidez_positiva_e_a_propria_base(self):
        q = com_colunas(4, nitidez=[1000, 1000, 400, 400])
        base = segmentos.normalizar(q, padrao())["foco"]
        pos = segmentos.normalizar(q, padrao(preferencias={"nitidez": 0.5}))["foco"]
        np.testing.assert_allclose(pos, base)

    def test_assunto_positivo_premia_assunto_ativo(self):
        q = com_colunas(4, movimento_assunto=[0.0, 0.04, 0.08, 0.08])
        mov = segmentos.normalizar(q, padrao(preferencias={"assunto": 1.0}))["movimento"]
        np.testing.assert_allclose(mov, [0.0, 0.5, 1.0, 1.0])

    def test_espelho_com_outra_preferencia_e_media_das_duas(self):
        q = com_colunas(4, movimento_assunto=[0.08] * 4, cam_dx=[0.0] * 4)
        mov = segmentos.normalizar(q, padrao(preferencias={"assunto": 1.0, "camera": 1.0}))["movimento"]
        np.testing.assert_allclose(mov, 1.0)   # (1·1 + 1·1) / 2, sem a base (que daria 0 para assunto 0,08)

    def test_outra_metrica_nao_muda(self):
        q = com_colunas(4, movimento_assunto=[0.0, 0.04, 0.08, 0.08])
        zero = segmentos.normalizar(q, padrao())
        ligada = segmentos.normalizar(q, padrao(preferencias={"assunto": 1.0}))
        for k in ("foco", "exposicao", "estabilidade"):
            np.testing.assert_allclose(ligada[k], zero[k])


class TestFlagsPelaBase(unittest.TestCase):
    """Preferências mudam a nota, não as flags: quadro borrado continua excluído."""

    def test_suave_estavel_com_estab_foco_continua_excluido(self):
        p = padrao(preferencias={"estab_foco": 0.4})
        self.assertEqual(p["flags"]["blur"], "excluir")
        sc = sidecar("A.MP4", n=40, nitidez=[4.0] * 40)   # foco base 0,1 (< limite de blur 0,35)
        norm, _, base = segmentos.normalizar_tudo(sc["quadros"], p)
        self.assertGreater(float(norm["foco"][0]), p["limites"]["blur"])   # a mistura passaria do limite
        self.assertLess(float(base["foco"][0]), p["limites"]["blur"])
        trechos, _ = segmentos.trechos_do_clipe(sc, p)
        self.assertEqual(trechos, [])

    def test_reajuste_tambem_usa_a_base(self):
        import reajuste
        sc = sidecar("A.MP4", n=40, nitidez=[4.0] * 40)
        notas = reajuste.notas_por_amostra(sc, padrao(preferencias={"estab_foco": 0.4}))
        np.testing.assert_allclose(notas, 0.0)

    def test_wrappers(self):
        q = com_colunas(8)
        p = padrao(preferencias={"detalhe": 0.5})
        norm, sub, base = segmentos.normalizar_tudo(q, p)
        n2, s2 = segmentos.normalizar_com_submetricas(q, p)
        for k in norm:
            np.testing.assert_allclose(segmentos.normalizar(q, p)[k], norm[k])
            np.testing.assert_allclose(n2[k], norm[k])
        self.assertEqual(set(s2), set(sub))
        for k in base:
            np.testing.assert_allclose(base[k], segmentos._normalizar_base(q, p)[k])

    def test_preset_sem_preferencias_nao_quebra(self):
        p = padrao()
        del p["preferencias"]
        trechos, _ = segmentos.trechos_do_clipe(sidecar("A.MP4", n=40), p)
        self.assertTrue(trechos)


class TestAnaliseAntiga(unittest.TestCase):
    def test_sem_coluna_a_preferencia_nao_entra(self):
        q = quadros_fake(4)   # sem detalhe, luma_p01, luma_p99
        self.assertEqual(segmentos.colunas_faltando(q), ["detalhe", "luma_p01", "luma_p99"])
        zero = segmentos.normalizar(q, padrao())["foco"]
        ligada = segmentos.normalizar(q, padrao(preferencias={"detalhe": 1.0}))["foco"]
        np.testing.assert_allclose(ligada, zero)

    def test_aviso_so_quando_uma_preferencia_precisa_da_coluna(self):
        sc = sidecar("A.MP4", n=40)
        _, avisos = segmentos.trechos_do_clipe(sc, padrao())
        self.assertFalse(any(a.startswith("sem_colunas") for a in avisos))
        _, avisos = segmentos.trechos_do_clipe(sc, padrao(preferencias={"folga_cor": 0.5}))
        self.assertIn("sem_colunas:detalhe,luma_p01,luma_p99", avisos)


class TestTrecho(unittest.TestCase):
    def test_trecho_grava_as_submetricas_disponiveis(self):
        sc = sidecar("A.MP4", n=40)
        sc["quadros"].update(detalhe=[0.05] * 40, luma_p01=[0.1] * 40, luma_p99=[0.9] * 40)
        trechos, _ = segmentos.trechos_do_clipe(sc, padrao())
        self.assertTrue(trechos)
        sub = trechos[0]["submetricas"]
        self.assertEqual(set(sub), set(presets.PREFERENCIAS))
        self.assertTrue(all(0.0 <= v <= 1.0 for v in sub.values()))

    def test_sem_colunas_novas_ficam_de_fora(self):
        trechos, _ = segmentos.trechos_do_clipe(sidecar("A.MP4", n=40), padrao())
        self.assertNotIn("detalhe", trechos[0]["submetricas"])
        self.assertNotIn("folga_cor", trechos[0]["submetricas"])


class TestCortesEJanela(unittest.TestCase):
    CORTE = [False] * 8 + [True] + [False] * 7

    def _sub(self, **over):
        q = com_colunas(16, corte=self.CORTE, **over)
        return segmentos.submetricas_quadros(q, np.ones(16))

    def test_estab_foco_nao_atravessa_corte(self):
        s = self._sub(nitidez=[1000.0] * 8 + [300.0] * 8)
        np.testing.assert_allclose(s["estab_foco"], 1.0)

    def test_flicker_nao_atravessa_corte(self):
        s = self._sub(brilho=[0.3] * 8 + [0.7] * 8)
        np.testing.assert_allclose(s["flicker"], 1.0)

    def test_estab_movimento_nao_atravessa_corte(self):
        s = self._sub(cam_dx=[0.0] * 8 + [0.06] * 8)
        np.testing.assert_allclose(s["estab_movimento"], 1.0)

    def test_timestamps_iguais_nao_quebram(self):
        segmentos.normalizar(com_colunas(5, t=[0.0] * 5), padrao())


if __name__ == "__main__":
    unittest.main()
