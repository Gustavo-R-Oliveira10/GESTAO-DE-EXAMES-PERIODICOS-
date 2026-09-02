# Fluxo de trabalho Git — passo a passo

Repositório: https://github.com/Gustavo-R-Oliveira10/GESTAO-DE-EXAMES-PERIODICOS-

## Regra de ouro

**`main` é sempre a versão que funciona.** Nunca mexa direto nela. Toda
alteração nasce numa branch separada e só volta pra `main` quando já testada.

## O ciclo, toda vez que for alterar algo

```
# 1. Garanta que está com a main atualizada
git checkout main
git pull

# 2. Crie uma branch nova pra essa alteração
git checkout -b nome-da-alteracao
   # ex: git checkout -b fix-calculo-progresso
   # ex: git checkout -b feature-painel-sp

# 3. Trabalhe normalmente (você ou eu editamos os arquivos)

# 4. Confira o que mudou antes de commitar
git status
git diff

# 5. Adicione e commite
git add -A
git commit -m "Descricao curta do que mudou e por que"

# 6. Suba a branch pro GitHub (funciona como backup remoto)
git push -u origin nome-da-alteracao

# 7. Quando a alteração estiver testada e você quiser trazer pra main:
git checkout main
git pull
git merge nome-da-alteracao
git push

# 8. (opcional) apague a branch que já foi mesclada
git branch -d nome-da-alteracao
git push origin --delete nome-da-alteracao
```

## Por que branch em vez de commitar direto na main

- Se uma alteração quebrar alguma coisa, `main` continua intacta — você só
  descarta a branch problemática.
- Cada branch some por um único assunto: mais fácil de entender depois "pra
  que serviu essa mudança".
- Nunca perde nada: toda branch enviada (`git push`) já está salva no GitHub,
  mesmo antes de virar main.

## Nomes de branch sugeridos

- `fix-...` para correção de bug (ex: `fix-data-agendada`)
- `feature-...` para funcionalidade nova (ex: `feature-painel-fila-sp`)
- `docs-...` para só documentação

## Mensagens de commit

Curtas, no imperativo, dizendo o quê e (se não for óbvio) por quê:

```
Corrige calculo de progresso da campanha
Adiciona filtro por local na consulta geral
Remove upload duplicado da lista do RH
```

## Se der conflito no merge

Acontece quando a mesma linha foi mexida em `main` e na sua branch ao mesmo
tempo. O Git avisa quais arquivos têm conflito — abra, procure por
`<<<<<<<`, `=======`, `>>>>>>>`, decida o que fica, apague essas marcações,
depois:

```
git add <arquivo resolvido>
git commit
```

## O que NUNCA vai pro Git (já configurado no `.gitignore`)

- `app/data/` inteira — banco (`periodicos.db`), a base mestre real
  (`base_mestra_2026.xlsx`), logs, PDFs de ASO. Tudo isso é dado real de
  funcionário, nunca deve subir pro GitHub, nem em repositório privado.
- Qualquer `.xlsx`/`.xls` em qualquer lugar do projeto.
- `__pycache__/`, `.venv/`, arquivos de log.

**Antes de todo `git add -A`, rode `git status` e olhe a lista** — se
aparecer algum `.xlsx`, `.csv`, `.db` ou coisa de funcionário, pare e me
avise antes de commitar.

## Comandos do dia a dia (resumo rápido)

| Quero...                          | Comando                          |
|------------------------------------|-----------------------------------|
| Ver o que mudou                    | `git status` / `git diff`         |
| Ver histórico                      | `git log --oneline`               |
| Trocar de branch                   | `git checkout nome-da-branch`     |
| Ver branches                       | `git branch -a`                   |
| Descartar mudança não commitada    | `git checkout -- arquivo`         |
| Trazer atualizações do GitHub      | `git pull`                        |
