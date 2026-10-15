# shellcheck shell=bash
# The box script of an AWS run (user_data.sh, ladder_user_data.sh or oracle_user_data.sh) with its placeholders filled:
# the one rendering, used by lib.sh (the launchers' dry runs and the tests) and by the bootstrap on the box
# (bootstrap_user_data.sh), so the box runs exactly what the dry run shows. Every value is validated before it gets
# here (lib.sh's checks at launch).
df_render_box() { # script campaign commit bucket max-minutes run-id resume(yes|no)
    sed -e "s|@CAMPAIGN@|$2|g" -e "s|@COMMIT@|$3|g" -e "s|@BUCKET@|$4|g" -e "s|@MAX_MINUTES@|$5|g" \
        -e "s|@RUN_ID@|$6|g" -e "s|@RESUME@|${7:-no}|g" "$1"
}
