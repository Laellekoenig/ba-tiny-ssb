function getChanges(oldV, newV) {
    if (oldV === newV) return [];

    // get lcs string
    mid = extractLCS(oldV, newV);

    // compute insert/delete operations
    let changes = [];

    // start with delete operations -> difference to original
    let j = 0;
    for (let i = 0; i < oldV.length; i++) {
        if (oldV[i] !== mid[j]) {
            // check for consecutive deletions
            const sIdx = i;
            let x = oldV[i];
            while(++i < oldV.length && oldV[i] !== mid[j]) {
                x = x.concat(oldV[i]);
            }
            changes.push([sIdx, 'D', x]);
            i -= 1;
            continue;
        }
        j += 1;
    }


    // compute insert operations -> difference to update
    j = 0;
    for (let i = 0; i < newV.length; i++) {
        if (newV[i] !== mid[j]) {
            // check for consecutive insertions
            const sIdx = i;
            let x = newV[i];
            while (++i < newV.length && newV[i] !== mid[j]) {
                x = x.concat(newV[i]);
            }

            changes.push([sIdx, 'I', x]);
            i -= 1;
            continue;
        }
        j += 1;
    }

    return changes;
}

function extractLCS(s1, s2) {
    // computes the lcs of two given strings

    // get grid
    mov = getLCSGrid(s1, s2);
    let lcs = "";

    // "walk" through grid
    // 0 -> left, 1 -> diagonal, 2 -> up
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

function getLCSGrid(s1, s2) {
    // computes the lcs grid of two strings
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
