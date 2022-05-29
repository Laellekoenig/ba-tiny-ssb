function getChanges(oldV, newV) {
    mid = extract_lcs(oldV, newV);
    let changes = [];

    console.log(oldV);
    console.log(mid);
    console.log(newV);

    let j = 0;
    for (let i = 0; i < oldV.length; i++) {
        if (oldV[i] !== mid[j]) {
            const sIdx = i;
            let x = oldV[i];
            while(++i < oldV.length && oldV[i] !== mid[j]) { 
                x = x.concat(oldV[i]);
            }
            changes.push(['D', sIdx, x]);
            i -= 1;
            continue;
        }
        j += 1;
    }

    j = 0;
    for (let i = 0; i < newV.length; i++) {
        if (newV[i] !== mid[j]) {
            const sIdx = i;
            let x = newV[i];
            while (++i < newV.length && newV[i] !== mid[j]) {
                x = x.concat(newV[i]);
            } 

            changes.push(['I', sIdx, x]);
            i -= 1;
            continue;
        }
        j += 1;
    }

    return changes;
}

function extract_lcs(s1, s2) {
    mov = lcs_grid(s1, s2);
    let lcs = "";

    let i = s1.length - 1;
    let j = s2.length - 1;

    while (i >= 0 && j >= 0) {
        if (mov[i][j] == 1) {
            lcs = s1[i] + lcs;
            i--;
            j--;
            continue;
        }
        if (mov[i][j] == 0) {
            j--;
            continue;
        }
        i--;
    }

    return lcs;
}

function lcs_grid(s1, s2) {
    const m = s1.length;
    const n = s2.length;

    // left = 0, diagonal = 1, up = 2 
    let mov = new Array(m).fill(-1).map(() => new Array(n).fill(-1));
    let count = new Array(m).fill(0).map(() => new Array(n).fill(0));

    for (let i = 0; i < m; i++) {
        for (let j = 0; j < n; j++) {
            if (s1[i] === s2[j]) {
                let val = 0;
                if (i > 0 && j > 0) {
                    val = count[i - 1][j - 1];
                }
                count[i][j] = val + 1;
                mov[i][j] = 1;
            } else {
                let top = 0;
                if (i > 0) {
                    top = count[i - 1][j];
                }

                let left = 0;
                if (j > 0) {
                    left = count[i][j - 1];
                }
                count[i][j] = top >= left ? top : left;
                mov[i][j] = top >= left ? 2 : 0;
            }
        }
    }
    return mov;
}
