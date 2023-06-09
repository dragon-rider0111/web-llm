import tvm
from tvm import IRModule
from tvm import relax, tir
from tvm.relax.dpl.pattern import is_op, wildcard
from tvm.relax.dpl.pattern import GlobalVarPattern, TuplePattern


def check_x_1dim(ctx: relax.transform.PatternCheckContext) -> bool:
    x = ctx.annotated_expr["x"]
    n = x.struct_info.shape[-2]
    return isinstance(n, tir.IntImm) and n.value == 1


def check_decoding(ctx: relax.transform.PatternCheckContext) -> bool:
    call = ctx.annotated_expr["w"]
    if (not isinstance(call, relax.Call)):
        return False
    gv = call.args[0]
    if (not isinstance(gv, relax.GlobalVar)):
        return False
    return gv.name_hint.startswith("decode")


def check_matmul(ctx: relax.transform.PatternCheckContext) -> bool:
    call = ctx.annotated_expr["matmul"]
    if (not isinstance(call, relax.Call)):
        return False
    gv = call.args[0]
    if (not isinstance(gv, relax.GlobalVar)):
        return False
    return gv.name_hint.startswith("matmul") or gv.name_hint.startswith("fused_matmul")


def pattern_check(ctx: relax.transform.PatternCheckContext) -> bool:
    return check_x_1dim(ctx) and check_decoding(ctx) and check_matmul(ctx)


def decode_matmul_pattern(match_ewise: bool):
    w_scaled = wildcard()
    scale_min = wildcard()
    x = wildcard()
    y = wildcard()
    w = is_op("relax.call_tir")(
        GlobalVarPattern(), TuplePattern([w_scaled, scale_min]), add_constraint=False
    )
    matmul_args = [x, w]
    if match_ewise:
        matmul_args.append(y)
    matmul = is_op("relax.call_tir")(
        GlobalVarPattern(), TuplePattern(matmul_args), add_constraint=False
    )

    annotations = {
        "matmul": matmul,
        "w": w,
        "x": x,
        "w_scaled": w_scaled,
        "scale_min": scale_min,
    }

    return matmul, annotations, pattern_check


@tvm.transform.module_pass(opt_level=0, name="FuseDecodeMatmulEwise")
class FuseDecodeMatmulEwise:
    def transform_module(self, mod: IRModule, ctx: tvm.transform.PassContext) -> IRModule:
        mod = relax.transform.FuseOpsByPattern(
            [("decode_matmul", *decode_matmul_pattern(match_ewise=False))]
        )(mod)
        mod = relax.transform.FuseOpsByPattern(
            [("decode_matmul_ewise", *decode_matmul_pattern(match_ewise=True))]
        )(mod)
        mod = relax.transform.FuseTIR()(mod)

        return mod
