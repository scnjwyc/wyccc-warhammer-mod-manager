"""Focused, versioned Three Kingdoms DB schema used by the unit-data editor.

The data is a compact copy of the relevant definitions from RPFM's
``schema_3k``.  Keeping only the tables used by this feature avoids shipping
the full multi-megabyte schema while still accepting the historical versions
that workshop mods commonly contain.
"""

from __future__ import annotations

import base64
import json
import zlib


# zlib + Base85 encoded JSON.  Regenerate from RPFM schema_3k by retaining the
# table name, version, field name and field type for the tables below.
_SCHEMA_B85 = (
    "c-rk<OOG5W68<lJ*pm-_v@OpZSK5|*SnXl8(n^+vs7xx8DKf!8R(E+c|9vAMs|rZS>h`wnZkwAsgW?fHd|wbe{O8p``ADXbTSF|}"
    "2xhK+|MTkl_0{hmKVH$c<(A8l3bL8FX!+O?%|1_Dvw@BF>c!Q+l$Zb8Y7qYC{ne)zAFmoZD9XE$G*m&E4{u)2pN(bkcU)F8Y8kP7"
    "U{TSLSWR2}_ID`-qoeyS=-9f>rqv9Suv`gxU^;0vl1O6%(Mb0&vbnnKNXBU(rsv9p6@tEC^h800C<{gOt|U^L8OytHkeW4m;ubZT"
    "_AC?)a?e?*gPIB6!RPx-OHOZ-+A*fm=5HDAdRuPO$VoTsK5gDgEm{Ke*MdsqC=SVlazorKB%h694Trg5-u}oy%`WI4jO6pg2p?N^"
    "ho9eF`^rYb#^%rnso;k+sZ%qjDAWRZ$Pnn%a!K}*H%#u)h`^vGy)fj7`>H!FCq>Xu*Gn9S9Tl;h>0q3oogQX_*dDzk8IO|M_V6dz"
    "`@l3^c!ZqRO@Ww(3iwp4Rt`!U4$f&BHWn>#V1hwmwDp^lhZw^}@)2FyaMq<RT~IH<KQwO_dPeu_85OoCTTL76QP2u{ndXfpcZzg~"
    "Y#dR@!_m_8KyMvG&`U(nff3+Pl3@bK()h3KBm{xF+1S}WHbwAWsu#0;0zo%u!cg1P88e^*DAZE?y4^Au!XET%OfZbII$(rSdy`39"
    "FpA!e2+3u2(6%9neTGm26FNeThR$V91OD{l>iT8H`-=A!?<?L{ynoJkpRI>%sI_i_Bm6(t4FvG!-H#=J0xlHsAAuTrRKoqr2+xKQ"
    "O4MH|;TuzeVNkPGl8><TFT>_Drj7@YLt6C;3~!}uQ+Mehyf#Yi!1MPq!#i?>p2*20q7a!rZxYzrO9DS_HSJ{D+gZd%Y3QUAp`2Au"
    "z}P_HMY~4Se_K(%qJBmFiux7xpEK$sl)tG^UZK1~d4=){<=+X)KmGOMjBnBI>2Ds3n`Y9qIRwp64O6O%sUx4yA%03D9JZ{J`mp$6"
    "Pj$!0MvhZdTu_%?ipsX!ICEk!_WaL+5`LnowX_L+w&w=4%E6XM%S@xWGZJFi-2#<%Y|-07rT%lvw&3?6whmHL!6N+S1J#GQbGMAD"
    "B##xAna%Q4Di4En+(FAK%J2c|GqG@d(}S;E9JNuj@opA>p7V$X`?JH`A2a#iPYQj~kS*87A_<vA7ywwyT^dlZJzJoU+-|`I^kVwa"
    "i0LBnx#xy&xZw7H)^Du~7w8Da0TdbL70c!5UAW&g7wUxEfRO+PI#UZvSm@Pe0;D<mW_D(<6$o`e2cWvp2+jhSiD?r^gp`1Y=NX8&"
    "2u#NNmh<koDJKJ?hxp2{Mvg6AdRkb>GHrRLOwV1o<r2R-LPO<HPRUyqen$lWdKgRXoEW~KlVj%y9R`_kjO24m2h2GSfOcC!qi8J<"
    "!9RGD7peYW(Af(=^e&bcQW5@&0&5x+W%1at#g1#JuutdhFg8R;peLE`S|)%3)By9ccShGvO_F$z;xZv=>%!MdMZNn0aRQ|q?8Y*6"
    "?mf#-02ebhEsXCtZwYc`b28WOD|uA%sN_+}qmsw3P98`HZz>(+=m4gjj-a?%srlt9#bkm7OnGcJal^&c_fo&BYj)RVv6iaxCBh0_"
    "rVJ}JKN+3<?Z*)s1rTl~LD4>eXQVsMkyQ)ym6sDDKR+>g#H&pC*i4CD?QP3ERsK8zc&q8u_14^<UenAN8x;Clm?QJFR@@%&2}x)?"
    "kKd@hxCoE**efstDUuVW8^Crgm11q02R(81p~%!|Z;X^04r{yl@ZW#_BcbuvKk0CBrWXZ*Y4!&UG6Y`cx}{ev_lmNdNHsgzDw&Np"
    "8F_9q=%}hw#FBG^BB2LFvS&SS1p7KBS&t0nov5rVoK1UBEE6h~w?(WR!G9r^!SuUc0Y(f(>s&t7xkNV%L&4AmU%ztm=0ny!X>iX<"
    "9~Qyvo`^Z9NWb%OOGg|1Bx3}gf5ItLWbw@ha=59pW6@?Mb{ays`LOLx6pzo+oId=n&nzi~Jg|W2kLx^(Lxc|SFZcWbZU_5+nkZZf"
    "%ea7p%$w9aiakzy@C!}A63uUm(xXk@oHq<zu&~%mhp+_NgE+XSrr7;P3ISmyR(u|TA9my@E5!iurD)~txL6q_tL0;-k>6haB1Tq?"
    ">w6m)LR++g4Z-czs}d<GSSC$?rs?rWSlv_5CQ(}cfr}OK6`+D!@9{F>7=MK^->aA3xNi^c6R7fBb+lvsuGH01y2$jfV$Ah}-6<j6"
    "<gddr&pX?>e;9mjqN5bB)<+ri2As^FZi$;d-mdVg==i`7A0S>>d<Vk><J%uY;PZ*2FJGVsdszH7J{~`z1=TwPG>j~M%6i?LTvs!<"
    "SiXrCWf$<u1ufvGO`1n==SC>kc+>^f=5$%&>}i^|JnG8^{Fns!%4nr5_(uE7Debx9oEYLT8dh3H>xV;sFxAitJl|Ea7Ch0>gJ#1;"
    "d@+PN*Xo?59EQnecT1hIB&x#+nU~W?j5P(gyhn!sayw0xTBM2K>pnKF&E%NN6Uc}7Bl=s*ypqnw7~LZ3<$!dcsHTG{btlZFT`2lB"
    "G=hi0JP(55ZloU5QE&MjE)_FQ7tEYuBeQxnxeGYM0SHo$hMsL09l+SYp?cz!m-N8>k`Wje9~5nDW(Zn}#T7-E0OO7Y?m@^7alipX"
    "+8oGHP0?aovn?KVg2l0>B4Eq3&DrASl}B0vfM|zZo+AN<IZ@1YEwVCrNeuJ2LLLy_qhaQkb#E*7SM0CYU$MVp|1-vZMDpv3<Q2&)"
    "l2;_JNM1m4JT4#z6}R{%&f+k^*W&zrgY(DW1H9|?TgCZ`^FJ%jSA4Jd{+;nXO^lyVG1^Bhrt@27Vc>Y*EQgV^loxiF0`bDc16ezr"
    "6rGV8#aLVT;Ss=2u-Ai~k4&sg*-Qz_?T8C@!F9H{^>9Qcvej~!jVqY&Vx>62{)E=${;WoV(FWEfXMecMEHp}JeB%-CZ-W2RU6DnD"
    "Dz;KbAnsJ?eJ(+N>IP!)OxN<H(eY^8k;tOmr{Ai%R&#wi=87iyzMABNP4cFi<hL}*w?CIjt}o+ys$HSeq+P_j;!J!;WBo~t6oX9n"
    "7K6XI<7O(1FXtB+y%1Jq6I(wEb>Wx_828)%r^fhj;e3!=`V*qK)FK03O2D%w5Kp@UI&rw{qvh<|y~iIe52Qy;vAaf01``BZdb(&;"
    "Y$-FI?dg5Yc$h-S+xTcGwmX-Oj>QyD7p2dZm}ygZQ>2)ZX*6Ra8U2lcoQSr6_yoy9zT;!&VUqcCX?d&JhNb2{C_?wJV#>UU8j7+{"
    "`)maTD^S!OrpsPDYNSBR3(u@2qOL63gy?oU*OaMpA?((KVYOgs;GsjV(nQpiMVsg`l%i$3t28hHxyB+vR}w@G;e$e?WuSb*_A3wH"
    "xWpIQ*r`j=L$>&yj(edfTVy_whZnt;1h-|d^2mu`F>-uy78wkd_bz|IEX!P0)NM{7;rFiaJ+_aTsiloB%-r+YA24-?)TCqM>9R@z"
    "Oo+Lq3IUMt#l1LuL`F%x@!6y+wOdMQ*ON0M<)2#erJx&3UwGCE9QyObj18)c(jzU`XN2|@qK3d5w!AA|8g)i-M%nd?Qk|xwC9{qC"
    "%U2G!FAQ=ER*UzvK;_IV$YHh|1eYVWWNX3ug3vZhRpVZMA|9l(Wd+_?TYZBoZIzsFrxxc5-w-R-d45y>sgXz4(<`G?MyZTa8KpAH"
    "Q)ZMm*OgHoi&0>rr;Xsajdam6j2ocbyQMMoaWBQ>*Y}rx`RKew-R+QKr5SOzF8&Urh^?+xoh{H^D)3Et7h7DZG$ZcT#ZQ~m!I36+"
    "0Kq#2VN@^Pc}>gAl(u+kbUgwnhYvM2cvx((P8ZKPcsO2z^9uDZx$b4*G1oHp<F(ZHl`$)0R>rK1SsC-I7}Gtc;a^=B{=Y1X4`F><"
    "MxER5rEc%}l=!bgwu?HG2g`o|8M~)|{45x9rqk#Monzw_s?C2sadi}E;i1mx>G+kG|Fu=kdQm(J@R+^JJZ+zQw&kz?0Uu?SnE"
)


# Additional composition, shield and battle-entity tables used by the Three
# Kingdoms-only unit fields.  Kept separately so the original focused schema
# stays easy to audit by feature.
_UNIT_DETAIL_SCHEMA_B85 = (
    "c%1E5J8#@D4E`^kGc*a%rWrdF=+vR;6a)g#qHXr{FeEw2CCGm-W%&}_*-EY`TC~V*21SV<$&U{|R4WKUp+FNT5PA_{rO;QG57qfu"
    "b$NAFt#MPGRNsOl(|*6Gu1~J2u<3DMb_;4Pe2*yk<TKxmLN}P14C)#cItXM<CYHD;t~+oo&K{Y>l6(MDqo}Rc7(dwJ3u+*3AH*c>"
    "t;ZL1d#cwQ4VH!6Bak%sOyE112P0~c7@f&fHTe8yhtziY+YLE}=xR}`U1(u&3vpD+-iq-kSfT9=-!-IJ<CC=t!DL$OQlL61FDPj;"
    ";~6_JGt;Qek}Rqga^vZK77!mCG;`H928yXC;(5S!#xxit*+kBbSfU*#o*670LLHeSX8D=!V$)z9{QmWhp6_}=t+AW}_KOL?s$Zrz"
    "*2Xdy$OLq5=tEi2+lJ|7l_DR(*rxFq#C^^(Fq~e}E1^J2bes+u(?gC4*Q4LdOz-Ru#!XzIqj`_Hn=^)G>OC3^shm>SN3<=zuI<oI"
    "HIR7*g9CBX+_C6uAJstZ1hTg-bc|cnpt*`mY9rGe)a%Hfd41fK581Y8NO24V$qd*SQ1C%Kd$S+ICuml4%~N0=*6eQyV+UTWl(lm2"
    "ooI=>gGRkVw||ysn4A~f6V}D&pPmpMf)t>LE4S-s4nOOG)4rg0eNvsD9^3Rk+@@oP=`9zp&#UR!yN|v5*t_3&?|wX~2E!!w9iftA"
    "iRAnD`%+(@^d&Z9FTDXZ><~E}vt>KD*{LS)BWpNHTo<z{NJTqU>pTV#Gk5SDW*R@SGi`^$4%qzvV&=($b6i=Jtcv{20u(!NW6i-7"
    "hhY)mGO`qhDTc*xL~dKEksG+%d4cEh>ASxU1ss71`}d0oKmI|0zX6Q%Is#BTKcg?REEz8aW*T-YYleIZAIwS3D-TcT5V*hPr8J7C"
    "GTh2Ju4n%X)<SAx22$BJV<$n=lG$lZr-?cedG^~4&nImqs$$oSYC{@+FW2<wXf(D+qjt#dCp3oyWNLV~2z}Y?)`7!&7jKEYA2e1;"
    "EGF|gy32uaFz{}fveoIhOpU8zNk3rSy<*YPxR@OHAg{7<`toj4j?6ZDhvj&?qQ3GJhUGOQ_RWhUw~pNUHEu=Pd^pnPP0;50@$n~)"
    "iPSm"
)


def load_three_kingdoms_schemas() -> dict[str, dict[int, tuple[tuple[str, str], ...]]]:
    raw = json.loads(zlib.decompress(base64.b85decode(_SCHEMA_B85)).decode("utf-8"))
    raw.update(
        json.loads(
            zlib.decompress(base64.b85decode(_UNIT_DETAIL_SCHEMA_B85)).decode("utf-8")
        )
    )
    # The focused compressed schema predates the unit disable workflow.  This
    # table is shared by Three Kingdoms and Warhammer III and is required to
    # block a disabled unit from being recruited through a building.
    raw.setdefault(
        "building_units_allowed_tables",
        {
            4: (
                ("building", "StringU8"),
                ("unit", "StringU8"),
                ("XP", "I32"),
                ("key", "I32"),
                ("conditions", "I32"),
                ("faction", "OptionalStringU8"),
                ("enabled", "Boolean"),
            )
        },
    )
    return {
        str(table_name): {
            int(version): tuple((str(name), str(field_type)) for name, field_type in fields)
            for version, fields in versions.items()
        }
        for table_name, versions in raw.items()
    }
